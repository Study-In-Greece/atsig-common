# Changelog

Tags have no `v` prefix. The services pin a tag in their `pyproject.toml`.

## 0.7.2

A fix only, nothing to change in a service.

### Fixed

- `atsig_common.observability` imported FastAPI at the top, for `setup_app`, so a
  worker without the `fastapi` extra (the Celery workers and the stream consumer of the
  email-service) could not use `init_observability`. FastAPI is now imported only by
  `setup_app`; `init_observability` and `scrub_sentry_event` need the `observability`
  extra only. `setup_app` without FastAPI raises `ImportError`.

## 0.7.1

Fixes only, nothing to change in a service: the public API and the signatures are
the same.

### Fixed

- `atsig_common.bootstrap` imported Redis, the R2/S3 storage and the API clients at the
  top, so `build_core(settings, redis=False, ...)` still needed the `redis` extra (and
  `storage`, `http`). They are now imported only when `build_core` builds them: a service
  without Redis (the uni-api) uses `build_core(settings, redis=False, api_clients=False)`
  without installing it. Asking for a client whose extra is missing raises `ImportError`
  from `build_core`, not at import time. A service that has the extras sees no change.
- `make_get_optional_auth_context` decoded the token itself, without the payload that
  `get_token_payload` keeps in `request.state`: a protected route whose policy is built
  from the optional context (the programmes-api) decoded the token twice. Both now share
  the decoded payload of the request, in whichever order they run. Only a valid token is
  kept, so an invalid one behaves as before (anonymous or 401 for the optional context,
  401 for the scope check).

## 0.7.0

Everything is additive and optional except the first item of the upgrade notes.

### Upgrade notes

- **`ProgrammeUpdateEvent.secretaries` is required** (it defaulted to `[]`). An event
  without the field used to read as "the programme has no secretaries" and cleared them;
  now it is refused by the validation. The producer (programmes-api) always sends the
  field. A service that kept a subclass only to make it required can drop it.
- **New base dependency: `tzdata`** (`atsig_common.time`). Images without system time
  zones, like the Alpine ones, need it for `ZoneInfo`.
- Pool settings: `BaseAtsigSettings.DB_POOL_SIZE` (10) and `DB_MAX_OVERFLOW` (20), the
  size of the pool of ONE process. The defaults are the pool of today, so nothing changes
  until a service sets them. Read them with `create_db_engine_from_settings(settings)`.
  A service overrides the defaults in its own settings class
  (`DB_POOL_SIZE: int = 5`) or per container with the environment.
- The base consumer logs the outcome that `process_message` returns, at debug level. A
  consumer that returns nothing behaves as before.

### Added

- `atsig_common.db.engine.create_db_engine_from_settings(settings, **overrides)`.
- `atsig_common.redis.consumer.ConsumerOutcome` (`applied`, `ignored`) and the return
  annotation `ConsumerOutcome | None` of `process_message`;
  `consumer_name_from_hostname(prefix)` for a name that does not change at a restart.
- `atsig_common.events`: `Actions.UNREADABLE` (the action an admin screen shows for a DLQ
  entry that can not be read back), `dlq_name(stream_name)` and `DLQ_SUFFIX`. The consumer
  uses `dlq_name`; the name is the same as before (`<stream>_dlq`).
- `init_observability(..., server_name=...)`: the name Sentry shows for the process (the
  web app and its worker). Not sent when it is not given.
- `atsig_common.time`: `ATHENS` and `today_athens()`.
- `atsig_common.email.dependencies.make_get_email_client(settings)` and
  `atsig_common.redis.dependencies.make_get_event_producer(redis_manager, **options)`:
  one client per process, with the return annotation that `make_service_factory` reads.
- `EventProducer(default_retries=0)`: `emit(retries=None)` uses it, an explicit value
  wins. A retry can publish an event twice, so the consumers must be idempotent.
- README: how to enable the issuer and audience checks, and what to look at first.

## 0.6.0

The package version in `pyproject.toml` was `0.5.0` while the last tag was `0.3.0`
(the services pinned `0.3.0`, which was the commit with version `0.5.0`). This release
takes the version and the tag back in line.

### Upgrade notes

For every service: change the pin to `@0.6.0` and run
`uv lock --upgrade-package atsig-common`. Then read what changes **behaviour**:

- **Consumers (`BaseRedisConsumer`)**
  - A stream entry that is not a valid message (no action/data, invalid JSON, data that
    is not an object) goes to the DLQ before it is ACKed. It used to be ACKed and lost.
  - A new consumer group starts at the beginning of the stream (`group_start_id="0"`),
    so events sent before the group existed are read. An existing group keeps its place.
  - The emergency ACK is gone: when the DLQ can not be written the message stays
    pending, and is taken again after `reclaim_idle_ms` (default 2 minutes, make it
    longer than the longest handling of one message). At start and every
    `reclaim_interval_s` the consumer reclaims pending messages (`XAUTOCLAIM`, needs
    Redis 6.2+). A message delivered more than `max_deliveries` (5) times goes to the DLQ.
  - `run()` gives up and raises after `max_loop_failures` (20) failed reads in a row,
    with a growing delay (5 s up to 60 s). The process then exits: **make sure the
    container has a restart policy**. `max_loop_failures=0` keeps the old behaviour
    (retry for ever). Cancelling the task now ends it as cancelled.
  - The slot of a failing message is free while it waits for the next attempt.
  - The DLQ and the logs get only the type of an unexpected exception (its text can hold
    values such as SQL parameters). `NonRetryableError` keeps its message: name fields
    and error types only.
- **Errors of other services (`BaseAPI`)**: an answer of another service that is not a
  400, 404 or 409 (its 401/403 for the token of this service, a 422, every 5xx) and
  every network error now become `UpstreamError`: **502** (504 for a timeout) with a
  generic message. They used to reach the user as the same 401/403, or as a 500 with the
  internal URL and the body of the other service. The frontends log the user out on a 401.
- **Authentication**: `decode_token` verifies with the cached keys of the realm
  (JWKS, refreshed after 10 minutes or when a token names an unknown key) instead of one
  request to Keycloak per token. When Keycloak is down and nothing is cached it raises
  `ServiceUnavailableError` (**503**, was a 401). `has_group` matches the group or its
  children, like the scope check (`/Applicants/Administrators` is no longer an admin).
  `iss`/`aud` checks exist but are **off**: set `KEYCLOAK_EXPECTED_ISSUER` /
  `KEYCLOAK_EXPECTED_AUDIENCE` only after trying them in a dev realm.
- **`/Helpdesk` is removed** from `GroupEnum` and `SUPER_GROUPS`. Routes that use
  `SUPER_GROUPS` accept `/Administrators` only.
- **Lists**: `?sort=` accepts only mapped columns and hybrid properties. Anything else
  falls back to the default order (it used to give a 500).
- **Validation errors (422)** no longer carry the `input` of each error.
- **Logs**: the access log writes the route template (`/references/{token}`), not the
  real path. `X-Request-ID` is kept only when it is up to 64 letters, digits, `.`, `_`
  or `-`.
- Removed (nothing in the services used them): `db.mixins.Base`, `RedisManager._instance`
  and `RedisManager._lock`.
- `email-service` was on `0.2.9`: the email module is unchanged since then, but the
  consumer, the exceptions and the enums changed as described above.

New optional settings (all have a default that keeps today's behaviour): `CORS_ORIGINS`
(JSON list), `LOG_USER_EMAIL`, `KEYCLOAK_EXPECTED_ISSUER`, `KEYCLOAK_EXPECTED_AUDIENCE`.

`BaseAtsigSettings.database_url` escapes `@` and `%` in the user and password (the
engine decodes them back). A credential that worked is unchanged. Alembic's `env.py`
should use `settings.alembic_database_url` (every `%` doubled) for
`config.set_main_option("sqlalchemy.url", ...)`.

### Added

- `atsig_common.auth.dependencies`: `build_auth_context`, `make_get_token_payload`,
  `make_get_auth`, `make_get_auth_context`, `make_get_optional_auth_context`
  (`on_invalid="anonymous"|"401"`), `make_get_policy`. The token is decoded once per request.
- `atsig_common.auth.decode`: `TokenVerifier`, `adecode_token`.
- `atsig_common.bootstrap`: `build_core(settings)` and `Core.make_lifespan(...)`.
- `atsig_common.observability`: `init_observability`, `setup_app`.
- `atsig_common.db.engine`: `create_db_engine` (pre-ping, recycle, hidden SQL parameters),
  `create_session_factory`.
- `atsig_common.files` (`detect_file_type`, `is_key_under_prefix`, `iter_file`,
  `temp_file`, `TempFileHelper`) and `atsig_common.middleware.body_limit`
  (`MultipartBodyLimitMiddleware`, status and message are parameters).
- `atsig_common.events`: `ApplicantNameSync`, `UserSyncEvent`, `UserDeleteEvent`,
  `ProgrammeUpdateEvent`, `Streams`, `Actions`, `validation_problems`. (The call event
  is not here yet.)
- `EventProducer`: `default_maxlen` / `maxlen`, `retries`, `emit_safe`. The producer
  writes the request id in a separate `meta` field. `BaseRedisConsumer`: `consumer_name`,
  `dlq_maxlen`, `reclaim_*`, `max_deliveries`, `max_loop_failures`, `group_start_id`.
- `ServiceTokenManager.aget_token`, async auth headers in `BaseAPI`,
  `AsyncEmailClient.asend_email` / `asend_bulk_emails` (the sync methods stay).
- `BaseAPI.path_segment`; `X-Request-ID` is sent with every call.
- `UpstreamError`, `ServiceUnavailableError` and their handlers.
- `LOG_USER_EMAIL` and `include_user_email` to keep the email out of the logs.
- Tests (`uv run pytest`) and a CI step.

### Fixed

- Ids placed in the path of a request are escaped, so an id can not reach another endpoint
  with the token of the service.
- `BaseAPI._request` failed when no `http_manager` was given.
- `UniCache` keys of the university and school paths never expired.
- `S3Storage.stop()` forgets the client; `RedisManager` closes with `aclose()`.
- `CRUDBaseService.update` no longer changes the dict it is given.
- `MultipartBodyLimitMiddleware` no longer lets `ClientDisconnect` escape after a refusal.
