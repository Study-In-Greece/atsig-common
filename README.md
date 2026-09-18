# atsig-common

Shared utilities package for the ATSIG (Study In Greece) microservices — `programmes-api`, `applications-api`, `profiles-api`, and any future services in the ecosystem.

## What's inside

- **Auth** (`atsig_common.auth`) — Keycloak group-based RBAC (`GroupEnum`, `validate_user_groups`), `BaseAuthContext`/`BaseAccessPolicy` for service-specific extension, JWT decoding.
- **Redis** (`atsig_common.redis`) — `RedisManager` connection wrapper, `EventProducer` for Redis Streams, `BaseRedisConsumer` (consumer groups, retries, Dead Letter Queue, graceful shutdown).
- **Services** (`atsig_common.services`) — `CRUDBaseService`/`CRUDBaseAuthService` generic base classes for SQLAlchemy-backed services.
- **Pagination** (`atsig_common.pagination`) — reusable query pagination helpers and response schemas.
- **Email** (`atsig_common.email`) — async email client with template + bulk send support.
- **API client** (`atsig_common.api_client`) — thin async HTTP client factory for service-to-service calls.
- **Exceptions** (`atsig_common.exceptions`) — shared error types (`BadRequestError`, `NotFoundError`, `NonRetryableError`, …) used consistently across services.
- **Logging / observability** (`atsig_common.logger`) — structured JSON logging, request-context middleware, Sentry integration.

Installed as an optional-extras package — each service pulls in only what it needs, e.g.:

```toml
atsig-common[fastapi,db,redis,auth] @ git+https://github.com/<org>/atsig-common@<tag>
```

## Requirements

- Python ≥ 3.13
- [uv](https://github.com/astral-sh/uv) for dependency management

## Local development setup

```bash
git clone git@github.com:Study-In-Greece/atsig-common.git
cd atsig-common
uv sync --all-extras
```

This creates a `.venv/` with every optional dependency group installed, plus dev tools (Ruff).

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
   - **patch** (`0.5.0` → `0.5.1`) — bug fixes, no new public API.
   - **minor** (`0.5.0` → `0.6.0`) — new public classes/functions, backward-compatible.
   - **major** (`0.x` → `1.0`, or `1.x` → `2.0`) — breaking changes to existing signatures/behavior.
5. Open a PR against `main`.

## Releasing

1. Merge the version-bump PR into `main`.
2. Tag the release:
```bash
   git tag v0.5.0
   git push origin v0.5.0
```
3. Create the GitHub release from the tag (`gh release create v0.5.0 --generate-notes`, or via the GitHub UI).
4. In each consuming service (`programmes-api`, `applications-api`, …), bump the pinned tag and refresh the lockfile:
```bash
   uv lock --upgrade-package atsig-common
```
   Commit the updated lockfile in that service's own PR.

## Notes on breaking changes

Because multiple independent services depend on this package, avoid silently changing behavior of existing public methods. Prefer additive changes (new method, new optional parameter with a safe default) over modifying existing ones. If a breaking change is genuinely necessary, call it out explicitly in the release notes and coordinate the upgrade across all consuming services before merging.
