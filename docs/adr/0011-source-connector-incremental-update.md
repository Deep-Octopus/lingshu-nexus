# ADR 0011: SourceConnector Incremental Update Baseline

Date: 2026-06-13

## Status

Accepted

## Context

T-100 requires new material to enter the system continuously while preserving the
existing raw, parsed, candidate, review, and published boundaries. The project
rules also state that external source contracts are not known yet: future sources
may return JSON, files, download references, or some combination of those, and we
must not invent PubMed, Crossref, CNKI, or local research-system fields before a
real sample exists.

The existing upload path parses documents but does not run the full incremental
candidate and review workflow. The existing candidate and release services
already enforce the important safety boundary: extraction writes candidate data
only, and publication still requires review and release activation.

## Decision

Add a `sources` module with:

- an internal `SourceArtifact` contract for JSON, file, and download-reference
  payloads;
- a `SourceConnector` port with fixture and generic REST adapters;
- a `SourceConnectorConfig` model with schedule metadata, max attempts, and
  secret-key validation;
- source sync runs and artifact records with idempotency keys, raw object refs,
  duplicate counts, retry lineage, and impact hints;
- a `SourceUpdateService` that sends mapped documents through the existing
  document parser, candidate extractor, and review-batch service.

The generic REST adapter only preserves raw responses and maps explicit internal
`SourceArtifact` shapes. It does not interpret unknown literature metadata. The
fixture adapter is used for deterministic offline tests of JSON, file, and
download-reference payloads.

Manual uploads now have a `sources:manual-sync` API path. Parsed documents are
extracted with the configured LLM provider. If live MiMo configuration is
missing, extraction fails as a recorded source run instead of fabricating
candidate evidence.

## Consequences

- New documents can produce candidate review batches and later new graph
  releases without bypassing review.
- Repeated syncs skip duplicate artifacts or duplicate document hashes, avoiding
  duplicate candidate batches.
- Raw responses and raw files are retained for debugging future connector
  contract changes.
- The frontend management console can show source configs, runs, duplicates,
  failures, and conflict hints.
- Specific external adapters and contract tests remain blocked until real
  endpoint, auth, request parameters, and response examples are available.
