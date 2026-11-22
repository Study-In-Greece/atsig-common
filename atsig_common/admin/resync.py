import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, params
from pydantic import BaseModel, ValidationError

from atsig_common.events.schemas import validation_problems
from atsig_common.events.tracking import spawn_background
from atsig_common.exceptions import BadRequestError, ConflictError, NotFoundError
from atsig_common.redis.manager import RedisManager

from .schemas import ResyncJobRead

logger = logging.getLogger("atsig_common.admin.resync")

# A lock that outlives a crashed process: the next run can start after this many seconds
LOCK_TTL_SECONDS = 3600
STATUS_TTL_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class ResyncJob:
    """
    A resync a service can run: it sends the events of its rows again.

    Attributes:
        name: The name in the URL (`universities`, `stats`, ...).
        description: What it sends, for the admin screen.
        run: Does the work and returns how many events it sent. It receives the
            validated parameters (a dict, empty without `params`). It must not close
            the shared Redis client: it runs inside the web process.
        params: Optional model of the parameters (`extra="forbid"` is applied).
    """

    name: str
    description: str
    run: Callable[[dict[str, Any]], Awaitable[int | None]]
    params: type[BaseModel] | None = None


def _status_key(name: str) -> str:
    return f"resync:{name}"


def _lock_key(name: str) -> str:
    return f"resync:{name}:lock"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def read_status(redis: RedisManager, job: ResyncJob) -> ResyncJobRead:
    raw = await redis.hgetall(_status_key(job.name))
    data = {
        (k.decode() if isinstance(k, bytes) else k): (
            v.decode() if isinstance(v, bytes) else v
        )
        for k, v in raw.items()
    }
    return ResyncJobRead(
        name=job.name,
        description=job.description,
        params=job.params.model_json_schema() if job.params else None,
        state=data.get("state", "idle"),
        count=int(data["count"]) if data.get("count") else None,
        error=data.get("error") or None,
        started_at=data.get("started_at") or None,
        finished_at=data.get("finished_at") or None,
    )


async def _run_job(redis: RedisManager, job: ResyncJob, values: dict[str, Any]) -> None:
    key = _status_key(job.name)
    try:
        count = await job.run(values)
        await redis.hset(
            key,
            {
                "state": "ok",
                "count": str(count if count is not None else ""),
                "error": "",
                "finished_at": _now(),
            },
        )
        logger.info(f"Resync '{job.name}' finished: {count} event(s)")
    except Exception as e:
        # Only the type: the text of an error can hold values
        await redis.hset(
            key,
            {"state": "error", "error": type(e).__name__, "finished_at": _now()},
        )
        logger.error(f"Resync '{job.name}' failed: {type(e).__name__}")
    finally:
        await redis.expire(key, STATUS_TTL_SECONDS)
        await redis.delete(_lock_key(job.name))


def make_resync_router(
    *,
    jobs: Sequence[ResyncJob],
    get_redis: Callable[[], RedisManager],
    dependencies: Sequence[params.Depends],
) -> APIRouter:
    """
    The admin router of the resync jobs of a service.

    - `GET /`: the jobs with the state of their last run.
    - `GET /{name}`: one job.
    - `POST /{name}` (202): starts the job in the background and answers at once. One
      run at a time per job (409 while it runs). The body may hold the parameters.

    The state lives in Redis (`resync:<name>`): the type of an error, never its text.
    """
    by_name = {job.name: job for job in jobs}
    router = APIRouter(dependencies=list(dependencies))

    def find(name: str) -> ResyncJob:
        job = by_name.get(name)
        if job is None:
            raise NotFoundError(f"Unknown resync '{name}'")
        return job

    @router.get("/", response_model=list[ResyncJobRead])
    async def list_jobs():
        redis = get_redis()
        return [await read_status(redis, job) for job in jobs]

    @router.get("/{name}", response_model=ResyncJobRead)
    async def get_job(name: str):
        return await read_status(get_redis(), find(name))

    @router.post("/{name}", response_model=ResyncJobRead, status_code=202)
    async def start_job(name: str, body: dict[str, Any] | None = Body(default=None)):
        job = find(name)
        redis = get_redis()

        values: dict[str, Any] = {}
        if job.params is not None:
            try:
                model = job.params.model_validate(body or {}, strict=False)
            except ValidationError as ve:
                raise BadRequestError(
                    f"Invalid parameters: {validation_problems(ve)}"
                ) from None
            values = model.model_dump(exclude_none=True)
        elif body:
            raise BadRequestError("This resync takes no parameters.")

        locked = await redis.redis.set(
            _lock_key(name), "1", nx=True, ex=LOCK_TTL_SECONDS
        )
        if not locked:
            raise ConflictError(f"The resync '{name}' is already running.")

        await redis.hset(
            _status_key(name),
            {
                "state": "running",
                "count": "",
                "error": "",
                "started_at": _now(),
                "finished_at": "",
            },
        )
        spawn_background(_run_job(redis, job, values))
        return await read_status(redis, job)

    return router
