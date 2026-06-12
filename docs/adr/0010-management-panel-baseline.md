# ADR 0010: Management Panel Baseline

Date: 2026-06-12

## Status

Accepted

## Context

T-090 needs a P0 management surface for documents, review decisions, graph
releases, jobs, Skills, and audit records. The project rules require candidate
data, published releases, chat retrieval, and Skill permissions to stay behind
server-side service boundaries. The current runtime adapters are still in-memory
for several domains, and SourceConnector scheduling is deferred to T-100.

## Decision

Add an `/api/v1/admin/*` aggregate route layer for management summaries, job
status, audit reads, and audited Skill management. The route layer reads from
existing document, review/release, Skill, and chat services instead of owning a
separate business state model.

Document upload, document reprocess, review decisions, release creation,
release activation, release rollback, Skill validation, Skill execution, and
chat verification continue to use their existing domain APIs. High-risk release
actions already write review audit events. Admin Skill upload and enable/disable
write explicit `skill.*` audit events.

Skill upload accepts package text for `SKILL.md`, `registry.yaml`, and
`tests/cases.yaml`. It requires an admin role, restricts Skill IDs to a safe
lowercase path segment, writes to a temporary package directory, validates with
the existing filesystem Skill loader, and only then replaces the live package
directory and upserts the registry entry. Uploaded Skills are not authorized by
prompt text; platform metadata in `registry.yaml` remains authoritative.

The admin overview exposes model cost as unavailable when no model usage
repository is mounted. It does not fabricate token totals or estimated costs.
Data-source and schedule controls are shown as a T-100 placeholder until the
`SourceConnector` contract is implemented.

## Consequences

- The Vue console can support the P0 operating loop without bypassing review,
  release, retrieval, or Skill authorization boundaries.
- Tests can verify the management path with in-memory services, including
  release activation and chat citation lookup.
- Skill upload is useful for internal development while remaining constrained
  to validated local packages.
- Production authentication, durable repositories, richer audit metadata, and
  full observability remain T-110 work.
