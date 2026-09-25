import inspect
from collections.abc import Callable
from typing import Any, TypeVar, get_type_hints

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


def make_service_factory(
    get_session: Callable[..., Any],
    **available_deps: Callable[..., Any],
) -> Callable[..., Callable[..., Any]]:
    """
    Returns a `get_service(service_cls, extra=[...])` factory,
    bound to your own `get_session`, `get_policy`, `get_email_client`, etc.
    Each API instantiates it once in its own
    `shared/deps/services.py`.
    """

    def get_service(
        service_cls: type[T], *, extra: list[str] | None = None
    ) -> Callable[..., T]:
        extra = extra or []
        unknown = set(extra) - available_deps.keys()
        if unknown:
            raise ValueError(f"Unknown service dependency(ies): {unknown}")

        async def _get_service(**kwargs: Any) -> T:
            return service_cls(**kwargs)

        params = [
            inspect.Parameter(
                "session",
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=Depends(get_session),
                annotation=AsyncSession,
            )
        ]
        for name in extra:
            dep_func = available_deps[name]
            # We get the type from the return annotation of the
            # dependency callable itself — you don't need to pass it.
            annotation = get_type_hints(dep_func).get("return", Any)
            params.append(
                inspect.Parameter(
                    name,
                    kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=Depends(dep_func),
                    annotation=annotation,
                )
            )

        _get_service.__signature__ = inspect.Signature(params)
        return _get_service

    return get_service
