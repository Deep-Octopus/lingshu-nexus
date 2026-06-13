# ADR 0012: V1 Security, Audit, and Observability Baseline

## Status

Accepted for T-110.

## Context

T-110 requires a minimum internal-research security baseline without inventing a
password system or binding the product to a specific institutional SSO before an
identity provider is available. Existing services already stored review, release,
Skill, source, and job records in memory for the V1 baseline, but write endpoints
accepted actor strings inconsistently and chat did not write audit events that
could reconstruct the answer path.

## Decision

Use a simplified V1 actor model:

- API callers provide `actor_id` and `actor_role` in the request body or form.
- Roles are `read_only`, `researcher`, `reviewer`, and `admin`.
- Server-side RBAC checks rank these roles before write actions. Request text,
  Skill prompts, and document content never grant permissions.
- Researcher or higher can upload/reprocess material.
- Reviewer or higher can review assertions and create immutable release
  snapshots.
- Admin is required to activate/rollback releases and manage SourceConnector or
  Skill status.

All high-value operations record audit events through the existing audit model:
document upload/reprocess, assertion review, release create/activate/rollback,
Skill upload/enable/disable/execute, SourceConnector configure/sync/retry, chat
answer completion/failure, and chat feedback. Chat audit stores the actor,
Skill execution id, release id/version, citation keys, query length, and query
SHA-256. It does not store the full query text.

Minimal structured observability is implemented with a standard-library
`ObservabilityRecorder`. It records sanitized JSON-shaped events for document
parse tasks, model extraction calls, source sync tasks, and chat answers. Events
include trace ids, domain ids, release ids when available, config versions,
metrics, and short error summaries. The recorder is in-memory for V1 and exposes
admin read endpoints for tests and local debugging.

Configuration status is exposed only as booleans and non-secret identifiers. API
responses mask secret references such as `env:SOURCE_TOKEN`, and source configs
continue to reject inline secret-looking keys.

## Consequences

- The V1 system has deterministic permission checks and auditable operator
  context without a custom password database.
- Production SSO/OIDC, durable audit repositories, and external telemetry sinks
  remain future adapters behind the same actor, audit, and observability shape.
- In-memory observability is not a production monitoring backend, but it makes
  task, model, and chat failures testable without adding dependencies.
- The prompt injection control is architectural: document and source text is
  treated as evidence data only; it is never evaluated as platform authorization
  or a backend command.
