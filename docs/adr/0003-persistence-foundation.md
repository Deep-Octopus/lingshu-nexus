# ADR 0003: Persistence Foundation

## Status

Accepted

## Context

T-020 needs durable boundaries for documents, chunks, candidate knowledge, review
decisions, releases, object artifacts, graph sync records, jobs, config versions,
and audit events. The project has selected PostgreSQL, object storage, and Neo4j
as infrastructure targets, but dependency installation and live database startup
are not guaranteed in the current sandbox.

## Decision

- Add SQL migration files under `backend/migrations/` using a conservative SQL
  subset that can be smoke-tested with SQLite and later applied to PostgreSQL.
- Use JSON stored as text in the first migration. A later SQLAlchemy/Alembic step
  can upgrade columns to PostgreSQL-native JSONB without changing the domain
  schema contract.
- Add object storage and graph repository ports with in-memory adapters for unit
  tests.
- Keep raw, parsed, candidate, published, and derived artifacts logically
  separated through an explicit `DataLayer`.
- Do not add pgvector in T-020. Vector storage belongs to the retrieval decision
  in T-060, when embedding model, retrieval baseline, and index ownership are
  evaluated together.

## Consequences

- T-020 can verify migration apply/drop/reapply and persistence invariants without
  network access or a running PostgreSQL container.
- PostgreSQL-specific optimization remains available later.
- Raw files and parsed/extracted artifacts are modeled as distinct immutable
  object records, preventing accidental overwrite.

