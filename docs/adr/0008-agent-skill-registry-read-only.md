# ADR 0008: Agent Skill Registry Read-only Baseline

Date: 2026-06-12

## Status

Accepted

## Context

T-070 requires versioned Agent Skills, platform-side permission metadata, safe
user-specified and automatic routing, and execution logs. The platform rules
explicitly prohibit relying on `SKILL.md` prompt text for authorization, and
chat-time automatic routing must be limited to enabled read-only Skills that
only read published active releases.

## Decision

LingShu Nexus stores Skill instructions in `skills/<skill-id>/SKILL.md` and
stores enforceable platform metadata in `skills/<skill-id>/registry.yaml`.
`SKILL.md` must include `name` and `description` frontmatter. `registry.yaml`
defines version, status, scope, domain ids, minimum role, server-side allowed
tools, supported query types, and checksum policy.

The T-070 runtime baseline uses an in-memory `SkillRepository` and a filesystem
loader for built-in packages. SQL migration `0006_skill_registry` records the
PostgreSQL table shape for versioned registry entries and execution logs.

Chat execution only accepts active `read_only` Skills whose allowed tools are in
the platform read-only allowlist. Automatic routing filters by status, role,
scope, allowed tools, domain, and query type before selecting a Skill. It never
selects background write Skills. Executions call `RetrievalService`, which reads
the indexed active release and does not access candidate repositories.

## Consequences

- Built-in V1 Skills are `evidence-query` and `literature-landscape`.
- The first Skill outputs deterministic, citation-backed evidence summaries for
  focused tVNS/taVNS questions.
- The second Skill summarizes active-release literature patterns and states
  missing metadata instead of fabricating timelines or trial details.
- Backend write Skills can be represented in registry metadata later, but are
  rejected by the chat execution path.
- No new runtime dependency is introduced for YAML parsing; registry files use a
  deliberately small YAML subset that is enough for current metadata.
