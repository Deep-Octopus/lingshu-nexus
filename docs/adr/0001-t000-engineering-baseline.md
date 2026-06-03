# ADR 0001: T-000 Engineering Baseline

## Status

Accepted

## Context

T-000 needs a runnable monorepo foundation without implementing the later evidence
schema, document processing, extraction, review, or retrieval features. The
project must keep API, Web, worker, domain primitives, config, tests, and docs
separate enough for later tasks to extend without rewriting the scaffold.

## Decision

- Use a single repository with `backend/`, `frontend/`, `packages/`, `config/`,
  `tests/`, `scripts/`, and `docs/`.
- Use FastAPI and Uvicorn for the API health-check scaffold.
- Use Vue 3, Vite, and TypeScript for the Web scaffold.
- Keep shared domain primitives in `packages/lingshu-domain` so later modules can
  depend on `domain_id` without tying themselves to the API package.
- Provide Docker Compose services for PostgreSQL, Redis, MinIO, and Neo4j, using
  local placeholder credentials only.
- Provide root `make` commands for lint, format check, type check, and tests.
  These commands run before third-party development dependencies are installed;
  when Ruff or Mypy are available, the quality script delegates to them.

## Consequences

- T-000 can be validated without network access or real credentials.
- Full FastAPI and Vue startup still requires installing declared Python and Node
  dependencies.
- Business schema, storage migrations, model providers, and graph/retrieval
  adapters remain explicitly deferred to later TODOs.

