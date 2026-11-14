# Changelog

Tags have no `v` prefix. The services pin a tag in their `pyproject.toml`.

## 0.15.0

### Added

- `atsig_common.turnstile.make_require_turnstile(get_secret)`: builds the FastAPI dependency
  that checks the Turnstile token of a public route (needs the `fastapi` extra). The form
  sends the token in the `X-Turnstile-Token` header (`TURNSTILE_HEADER`); the route declares
  the check like it declares its authentication:
  `dependencies=[Depends(require_turnstile)]`. The IP of the caller (first address of
  `X-Forwarded-For`, else the connection) goes to Cloudflare as `remoteip`. An empty secret
  turns the check off. `get_secret` is called on every request.

### Upgrade notes

- No existing API changes: `verify_turnstile` stays as it is. A service that moves the check
  from its service layer to a dependency also removes the `turnstile_token` field of its
  schemas, and its form sends the header instead.

## 0.14.0

### Added

- `atsig_common.turnstile.verify_turnstile(token, secret, remote_ip=, ...)`: server-side
  check of a Cloudflare Turnstile token for public forms (needs the `http` extra). An empty
  secret turns the check off (local development). A missing or rejected token raises
  `BadRequestError`; Cloudflare unreachable or a bad answer raises `ServiceUnavailableError`
  (fails closed). The token is never logged.

### Upgrade notes

- No existing API changes. A service that wants the check declares
  `TURNSTILE_SECRET: str | None = None` in its Settings and calls `verify_turnstile`.

## 0.13.0

**Breaking.** The applicants, the agents and the evaluators moved from the profiles-api
to the applications-api, so the client of the profiles-api and the event that kept the
names of the applications in sync are gone. No service uses them any more (the
applications-api stopped when the users moved there, the profiles-api when its applicant
and agent code was removed).

### Removed

- `UsersAPI` (`atsig_common.api_client.clients.users_api`), `APIClientFactory.get_users_api`
  and `PROFILES_API_URL` in `APIClientSettingsProto`.
- `ApplicantNameSync` and `Streams.APPLICANT_NAMES` (`update_applicant_applications`):
  nobody produces or consumes the event any more. The names of an applicant are read
  from its user row.

### Changed

- The documentation of `UserSyncEvent` and `UserDeleteEvent` says that two services
  produce them (the applications-api for applicants, agents and evaluators, the
  profiles-api for secretaries). The events themselves are the same.
- `build_core(settings, api_clients=True)` needs only `UNI_API_URL`.

### Upgrade notes

- A service must not import `UsersAPI` or `ApplicantNameSync`, nor call
  `core.api_factory.get_users_api()` (the applications-api and the profiles-api no longer
  do). Check with `grep -rn "UsersAPI\|get_users_api\|ApplicantNameSync\|APPLICANT_NAMES"`.
- `PROFILES_API_URL` can be removed from the settings and the stacks of the services
  that still carry it; it is ignored.
- The Redis stream `update_applicant_applications` and its `_dlq` can be deleted.

## 0.12.0

Additive: the identity layer of the users, shared by the services that keep accounts
(the profiles-api today, the applications-api next). Nothing existing changes.

### Added

- `atsig_common.users` (needs the `db`, `fastapi`, `redis` and `auth` extras):
  - `UserMixin`: the columns of the `user` table (`uuid` = the id in Keycloak, `email`
    unique and indexed, names, `is_active`, `group_path`). A service declares
    `class User(TimestampBase, UserMixin)` with its own relationships; the table is the
    same as before (`alembic revision --autogenerate` stays empty).
  - `UserCreate` (no password), `UserLocalCreate`, `UserUpdate`, `UserRead`, `UserBase`.
  - `UserService(user_model, session, kc_service, producer)`: `create_user` (Keycloak
    first, then the local row, a failed flush removes ONLY an account this request
    created), `update_user`, `delete_user` (database first, Keycloak and the event after
    the commit), `sync_local_user` (JIT), `create_local_user_only`,
    `update_local_user_only`, `get_user_by_email`, `read_users_by_uuids`, and `commit()`:
    commits, removes the new accounts if that fails, and only after a successful commit
    asks Keycloak to email each new account its invitation. The `user_events` stream
    gets `UserSyncEvent` / `UserDeleteEvent` from here (`emit_safe`).

### Fixed

- `read_users_by_uuids` filtered on `User.id`, which the model does not have; it now
  filters on `uuid`.

### Upgrade notes

- Nothing breaks. The profiles-api moves to it in its own change.
- A service subclasses `UserService` only when it needs more (a thin subclass that passes
  its `User` model is enough).

## 0.11.0

Additive: the Keycloak admin side of the users, shared by the services that create
accounts. Nothing existing changes.

### Added

- `atsig_common.keycloak_admin` (needs the `auth` extra): `KeycloakUserService(admin)`
  (moved from the profiles-api, with the same behaviour: async wrappers that take turns
  in a thread, `adelete_user` with retries, `get_user_by_id_with_retry`, error messages
  without the Keycloak answer), `create_keycloak_admin(settings)`, and the schemas
  `KeycloakUserCreate` / `KeycloakUserUpdate`.
- No password anywhere: `KeycloakUserCreate` has no `password`. A new account is created
  with the required actions `UPDATE_PASSWORD` and `UPDATE_PROFILE`, and
  `invite_user` / `ainvite_user` ask Keycloak to email the user the link
  (`send_update_account`, lifespan 3 days). The invitation never raises (it returns
  False): the account exists and can be invited again. The realm needs an SMTP server.
- `NewIdentityTracker`: keeps the Keycloak accounts that one request created and removes
  exactly those when the request fails (`discard`, `discard_all`,
  `commit_or_discard(session)`), the logic that `UserService` of the profiles-api had.
- `BaseAtsigSettings.KEYCLOAK_ADMIN_CLIENT_ID` / `KEYCLOAK_ADMIN_CLIENT_SECRET`
  (optional, None). A service that creates accounts must set them.

### Upgrade notes

- Nothing breaks. The profiles-api keeps its own copy until it moves to
  `atsig_common.keycloak_admin`, which removes the passwords from its create routes.
- A service that declares `KEYCLOAK_ADMIN_CLIENT_ID: str` in its own `Settings` (the
  profiles-api) keeps it required.
- A worker that creates accounts (the applications-api consumer creates the evaluators)
  needs the two settings too.

## 0.10.0

Additive: new events, a new stream name set and a way to drop `UniCache` entries.

### Added

- `UniversityEvent`, `SchoolEvent`, `DepartmentEvent` and `UniDeleteEvent` in
  `atsig_common.events`, and `Streams.UNI_UNIVERSITIES` (`uni_university_updates`),
  `Streams.UNI_SCHOOLS` (`uni_school_updates`), `Streams.UNI_DEPARTMENTS`
  (`uni_department_updates`): the academic catalogue of the uni-api as full snapshots,
  one stream per entity. `version` grows with every change and a consumer ignores a
  version that is not newer than the one it stores; `action=delete` carries a
  `UniDeleteEvent` (the last version plus one). The relations are plain ids (the three
  streams arrive in any order, a consumer must not expect the parent to exist).
  `UniversityEvent.image_url` is the public URL as the uni-api returns it. Nobody
  produces or consumes them yet; the uni-api produces, the programmes-api consumes,
  and the statistics-api will.
- `atsig_common.redis.uni_cache_keys`: the key templates of the `UniCache` (`DEPT_KEY`,
  `SCHOOL_KEY`, `UNI_HASH_KEY`) and `invalidate_uni_cache(redis, department_ids=,
  school_ids=, university_ids=)`, which drops the entries that a change of the uni-api
  made stale. It never raises (a failure is logged by the type of the error, the entries
  expire with their TTL) and does not import the `UniAPI` client, so the uni-api can use
  it without the `api_client` extra.

### Changed

- `UniCache` takes its key templates from `uni_cache_keys`. The attributes
  (`DEPT_KEY`, `SCHOOL_KEY`, `UNI_HASH_KEY`) and the behaviour are the same.
- `UniCache.CACHE_TTL` is 24 hours (was 1 hour). The uni-api drops the entries it
  changes with `invalidate_uni_cache`, so the TTL only covers what the invalidation
  misses (a failed Redis call, a change made outside the API such as the seeder or SQL).

### Upgrade notes

- Nothing breaks. There is nothing to do in a service that does not use the new events
  or `invalidate_uni_cache`.
- A service that uses `UniCache` now keeps a department for 24 hours instead of 1. Until
  the uni-api produces the invalidation, a change of the uni-api reaches it up to 24
  hours late: bump the services and deploy the uni-api together.

## 0.9.0

Additive, except that the payload of `ProgrammeUpdateEvent` now carries more keys.

### Added

- `CallEvent` (with `CallRequestedDocumentEvent`, `CallDisciplineEvent`,
  `CallExtraFieldEvent`) in `atsig_common.events`: the event of `calls_events`, defined
  once. Before, the programmes-api built it from the API schema of a call and the
  applications-api read it with another model. The fields that no consumer stores
  (`created_at`, `updated_at`, `is_open`, `call_file_url`) are not part of it; they are
  ignored if an older producer still sends them. `is_archived` is the call's own flag.
- `ProgrammeUpdateEvent` is now a full snapshot of the programme: `admission_type`,
  descriptions, contact data, languages, topics, study modes, tuition fees (nested
  `TuitionFeeEvent`), `masters_id`, `is_featured`, timestamps, and the fields of one kind
  of programme (`semesters`, `part_time`, `part_time_semesters`, `scholarship_offered`,
  `master_type`, `bachelor_type`, `days`, `short_term_type`). All of them are optional,
  so an event that is already in a stream, or sent by an older producer, still
  validates. The enums of the programmes-api travel as plain strings.
- `LeadEvent` and `Streams.LEADS` (`programme_leads`): a lead was saved. It carries the
  name, email and phone of a visitor: the producer must cap the length of the stream
  (`maxlen`), and a consumer must not log it. Nobody consumes it yet.

### Changed

- `ProgrammeUpdateEvent.is_archived` is the programme's own flag. The programmes-api used
  to send `not is_available_for_application` (it was also `true` for a programme that
  does not take applications through the system); the consumer now decides that from
  `admission_type` (`internal` takes applications) and `is_archived`.
- `ProgrammeUpdateEvent.to_payload()` has all the keys of the model, with `None` for what
  the producer did not set. A consumer that validates with the model sees no difference.

### Upgrade notes

- Nothing breaks. Rollout order for the change of meaning of `is_archived`: the consumer
  (applications-api) first, then the producer (programmes-api), then `manage.py resync
  programmes` and `resync calls`. Until the resync, a consumer sees `admission_type` as
  `None` on the rows it has and has to treat `is_archived` as it did before.
- A producer of `CallEvent` sends `to_payload()`; a consumer validates with `CallEvent`
  and logs `CallEvent.unexpected_keys(payload)` by name.

## 0.8.0

Additive: nothing changes in a service until it uses the new schemas.

### Added

- `atsig_common.schemas` with two response models, `IdRead` (`{"id": int}`) and
  `FileUrlRead` (`{"url": str}`), for the routes that answer a delete or a signed URL.
  They have exactly the fields of the plain dicts those routes returned, so the JSON of
  a route does not change when it declares `response_model=IdRead`; only OpenAPI gets
  the schema (and a wrong field can not slip into the body unnoticed).

### Upgrade notes

- Nothing is required. To use them: `response_model=IdRead` on the delete routes that
  return `{"id": ...}` (the id must be an integer: a route that returns a UUID string
  needs its own model) and `response_model=FileUrlRead` on the routes that return
  `{"url": ...}`. Compare the body of a route before and after.

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
