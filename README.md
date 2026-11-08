# atsig-common

Shared utilities package for the ATSIG (Study In Greece) microservices — `programmes-api`, `applications-api`, `profiles-api`, and any future services in the ecosystem.

## What's inside

- **Auth** (`atsig_common.auth`) — Keycloak group-based RBAC (`GroupEnum`, `validate_user_groups`), `BaseAuthContext`/`BaseAccessPolicy`, token verification with cached signing keys (`decode_token`, `adecode_token`, `TokenVerifier`), and the shared FastAPI dependencies (`auth.dependencies`: the token is decoded once per request).
- **Bootstrap** (`atsig_common.bootstrap`) — `build_core(settings)`: Keycloak, Redis, storage and API clients built from the settings, with a lifespan that starts and stops them in order.
- **Observability** (`atsig_common.observability`, `atsig_common.logger`) — `init_observability` (JSON logging, Sentry), `setup_app` (handlers, request-context middleware, CORS, debug route outside production), request ids that travel with calls and events.
- **Redis** (`atsig_common.redis`) — `RedisManager`, `EventProducer` (optional `maxlen`, retries, `default_retries`, `emit_safe`), `BaseRedisConsumer` (consumer groups, retries, Dead Letter Queue, reclaim of pending messages, graceful shutdown, `ConsumerOutcome`, `consumer_name_from_hostname`), `UniCache` (and `invalidate_uni_cache` to drop its entries), and `make_get_event_producer`.
- **Events** (`atsig_common.events`) — the events the services send each other, defined once (`ApplicantNameSync`, `UserSyncEvent`, `ProgrammeUpdateEvent` (a full snapshot of the programme), `CallEvent`, `LeadEvent`, `UniversityEvent`/`SchoolEvent`/`DepartmentEvent`, ...), the stream names and the names of the dead letter streams (`dlq_name`).
- **Files** (`atsig_common.files`, `atsig_common.middleware`) — upload type detection from the bytes, storage key checks, temporary files, and the multipart body limit middleware.
- **Database** (`atsig_common.db`) — `create_db_engine` / `create_db_engine_from_settings` (pool size from `DB_POOL_SIZE` and `DB_MAX_OVERFLOW`) / `create_session_factory`, `IDMixin`, `TimestampMixin`.
- **Services** (`atsig_common.services`) — `CRUDBaseService`/`CRUDBaseAuthService` generic base classes and the service dependency factory.
- **Pagination** (`atsig_common.pagination`) — pagination helpers and response schemas (sorting is limited to mapped columns and hybrid properties).
- **Schemas** (`atsig_common.schemas`) — `IdRead` and `FileUrlRead`, the response models of the routes that answer `{"id": ...}` (a delete) or `{"url": ...}` (a signed URL).
- **Email** (`atsig_common.email`) — email client with template + bulk send support (`asend_email` for async code), and `make_get_email_client`.
- **Time** (`atsig_common.time`) — `today_athens()`: the date in Greece, whatever the time zone of the container is (containers run in UTC).
- **API client** (`atsig_common.api_client`) — async HTTP client factory for service-to-service calls (errors of the other service become `UpstreamError`, a 502).
- **Exceptions** (`atsig_common.exceptions`) — shared error types used consistently across services.

Installed as an optional-extras package — each service pulls in only what it needs, e.g.:

```toml
atsig-common[fastapi,db,redis,auth] @ git+https://github.com/<org>/atsig-common@<tag>
```

## Enabling the issuer and audience checks

`KEYCLOAK_EXPECTED_ISSUER` and `KEYCLOAK_EXPECTED_AUDIENCE` (both off by default) make the
token verification stricter. What we found out about a real Keycloak (one realm, one
Keycloak client per frontend, one client for all the APIs):

- **Issuer** (`https://<keycloak-host>/realms/<realm>`): the `iss` of a token is the
  address the token was asked from, unless the hostname of Keycloak is fixed. When it is
  fixed, the tokens of the browsers and the service tokens (client credentials, asked
  through the internal address) have the SAME `iss`, and one value works for everybody.
  Check it first: decode (locally) a token of each frontend and a service token and
  compare `iss`. If they differ, a single expected issuer rejects one of them.
- **Audience**: `aud` is not a policy, it comes from the roles of the user (the
  "audience resolve" mapper): `account`, the names of clients whose roles the user has.
  No token carries the client of the APIs unless you add it. To turn the check on, add an
  Audience mapper (included client audience = the client of the APIs) in a shared client
  scope, assign it as a DEFAULT scope to every frontend client AND to the client of the
  APIs (for the service tokens), wait until the old tokens expire, check the claims, and
  only then set `KEYCLOAK_EXPECTED_AUDIENCE`. Skipping the client of the APIs breaks
  every service-to-service call. Assigning the scope only as a realm default scope is not
  enough: that applies to new clients only.
- The signature already ties a token to the keys of the realm (the keys come from its
  JWKS), so the issuer check adds little on its own; the audience check protects against
  a token issued in the same realm for another client.
- Decode a token without sending it anywhere:
  `python3 -c "import sys,base64,json;t=sys.argv[1].split('.')[1];print(json.loads(base64.urlsafe_b64decode(t+'='*(-len(t)%4))))" "<token>"`
  (read only `iss`, `aud`, `azp`).

## Requirements

- Python ≥ 3.13
- [uv](https://github.com/astral-sh/uv) for dependency management

## Local development setup

```bash
git clone git@github.com:Study-In-Greece/atsig-common.git
cd atsig-common
uv sync --all-extras
```

This creates a `.venv/` with every optional dependency group installed, plus dev tools (Ruff, pytest).

## Tests

```bash
uv run pytest
```

The tests are pure logic: no database, no network, no real Redis (a `FakeRedis` in `tests/conftest.py` records the commands). Add a test with every fix.

## Linting & formatting

We use **Ruff** for both linting and formatting — no Black, no separate isort.

```bash
# Check for issues
uv run ruff check .

# Auto-fix what's safe to fix
uv run ruff check . --fix

# Format code
uv run ruff format .
```

Configuration lives in `pyproject.toml` under `[tool.ruff]`, and mirrors the config used in `programmes-api` / `applications-api` (target `py313`, line-length 88) so linting stays consistent across the whole ecosystem.

**VS Code**: open the repo and accept the recommended extensions prompt (`.vscode/extensions.json`) — Ruff runs as the default formatter with format-on-save and import organizing already configured in `.vscode/settings.json`.

## Making changes

1. Branch off `main`.
2. Make your change. Keep it scoped — this package is a dependency of multiple live services, so unrelated cleanup (e.g. docstring rewrapping, generic-class refactors) belongs in its own PR, not mixed into a feature change.
3. Run `uv run pre-commit install` once after cloning, so Ruff runs
   automatically on every commit.
4. Bump `version` in `pyproject.toml` following semver:
   - **patch** (`0.6.0` → `0.6.1`) — bug fixes, no new public API.
   - **minor** (`0.6.0` → `0.7.0`) — new public classes/functions, backward-compatible.
   - **major** (`0.x` → `1.0`, or `1.x` → `2.0`) — breaking changes to existing signatures/behavior.
5. Open a PR against `main`.

## Releasing

1. Merge the version-bump PR into `main`.
2. Tag the release. Tags have no `v` prefix (`0.3.0`, `0.6.0`):
```bash
   git tag 0.6.0
   git push origin 0.6.0
```
3. Create the GitHub release from the tag (`gh release create 0.6.0 --generate-notes`, or via the GitHub UI), with the section of `CHANGELOG.md` as notes.
4. In each consuming service (`programmes-api`, `applications-api`, `profiles-api`, `uni-api`, `email-service`), bump the pinned tag in `pyproject.toml` (`...atsig-common.git@0.6.0`) and refresh the lockfile:
```bash
   uv lock --upgrade-package atsig-common
```
   Commit the updated lockfile in that service's own PR. Follow the "Upgrade notes" of the release in `CHANGELOG.md`.

## Notes on breaking changes

Because multiple independent services depend on this package, avoid silently changing behavior of existing public methods. Prefer additive changes (new method, new optional parameter with a safe default) over modifying existing ones. If a breaking change is genuinely necessary, call it out explicitly in the release notes and coordinate the upgrade across all consuming services before merging.
