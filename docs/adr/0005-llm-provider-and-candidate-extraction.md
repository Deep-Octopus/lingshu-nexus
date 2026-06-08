# ADR 0005: LLM Provider and Candidate Extraction

## Status

Accepted

## Context

T-040 needs a MiMo-backed extraction path from parsed chunks to candidate
EvidenceAssertion records. The platform rules require provider calls to stay
behind adapters, candidate knowledge to remain separate from published graph
data, and missing API keys not to block deterministic tests.

## Decision

- Add an `LlmProvider` port and keep provider-specific HTTP behavior inside
  `MiMoProvider`.
- Add `httpx` as a runtime dependency for HTTP provider calls. It is a mature
  Python HTTP client under a BSD-style license, already used by FastAPI/Starlette
  test ecosystems, and can be removed if a future MiMo SDK or gateway adapter
  replaces direct HTTP.
- Configure MiMo only through environment variables. API keys are never committed
  and are never serialized into candidate artifacts.
- Treat the MiMo adapter as a configurable chat-completions-compatible transport
  until the real MiMo endpoint is supplied and verified. The adapter refuses live
  calls when `MIMO_BASE_URL`, `MIMO_API_KEY`, or model configuration is still a
  placeholder.
- Add `FakeLlmProvider` for deterministic offline tests.
- Store generated results as candidate-layer artifacts through `DataLayer.CANDIDATE`
  and as in-memory run records for current tests. The 0003 migration records the
  PostgreSQL table shape for later repository implementation.
- Reject provider output that is not JSON, has no evidence assertions, or cites
  chunk ids outside the parsed document.

## Consequences

- Candidate extraction can be verified without real MiMo credentials.
- Later providers can be added without changing the extraction service tests.
- Model output cannot bypass review: all generated EvidenceAssertion records stay
  in `ReviewStatus.PENDING` and are not publishable until later review tasks.
- Live MiMo integration still requires real endpoint/key/model settings and a
  sample document run before claiming provider-level success.
