# V1 Acceptance Record

Date: 2026-06-15

## Decision

- Fixture-backed automated V1 flow: **passed**.
- Real acupuncture/tVNS release acceptance: **blocked `[?]` by external input**.
- Browser demonstration with real extraction and evidence: **not yet ready**.

The repository can now repeatably demonstrate the full application workflow with
clearly labeled synthetic fixtures. It cannot yet claim a real-domain V1 release
or model/retrieval quality result.

## Verified Fixture Flow

The T-120 API-level regression verifies:

1. Markdown fixture upload, raw storage, parsing, and stable chunk locators.
2. Fake-provider structured extraction into two candidate assertions.
3. Researcher review and release activation attempts are rejected by RBAC.
4. Only the reviewer-approved assertion enters the release; the pending safety
   assertion is excluded and cannot be released.
5. The active release is indexed and queried through `evidence-query` and
   `literature-landscape`.
6. SSE returns the release version and a document/chunk locator citation.
7. A candidate-only safety phrase does not appear in the answer or citations.
8. A second release can be activated and rolled back to the first release.
9. Source sync, review, release, chat, Skill execution logs, and rollback remain
   auditable.

The evaluation assets also validate the required tVNS question categories, 15
scope/refusal seeds, and the known terminology distinctions for Cymba Conchae,
cavum conchae, tragus, depression, blues, and Postpartum blues.

## Commands And Results

```bash
env UV_CACHE_DIR=.uv-cache uv run python scripts/run_v1_acceptance.py
```

Result: 51 relevant backend tests passed; the Vue/TypeScript production build
completed successfully.

```bash
env UV_CACHE_DIR=.uv-cache PYTHONPYCACHEPREFIX=/private/tmp/lingshu-nexus-pycache \
  make quality PYTHON='uv run python'
```

Result: Ruff lint and format passed, Mypy passed for 73 source files, and all 66
unit tests passed.

## V1 Acceptance Checklist

| V1 condition | Result | Evidence or remaining gate |
|---|---|---|
| Import PDF/Markdown and inspect status | Partial `[?]` | Markdown fixture and PDF parser tests pass; real Chinese PDF/Markdown parsing success rate awaits E-001. |
| Produce source-located candidate assertions | Partial `[?]` | Fixture Schema/locator flow passes; live MiMo extraction awaits E-005 and real files. |
| Review candidates and activate a release | Passed for V1 baseline | API regression covers RBAC, preview, creation, activation, exclusion, and audit. |
| Stream active-release answers with citations | Passed for fixture baseline | SSE regression returns release metadata and chunk locator; real citation quality awaits the real benchmark. |
| Execute and record two read-only Skills | Passed for fixture baseline | Both built-in Skills execute and produce execution records over the active release. |
| Run a controlled incremental update | Partial `[?]` | Manual/fixture connector regression passes; a real external adapter awaits E-006. |
| Inspect audit, failures, release/rollback, and config status | Passed for V1 baseline | Existing admin/security tests and T-120 rollback regression pass. |
| Repeat core tests with no candidate leakage | Passed for fixture baseline | Unified acceptance command plus full quality suite pass. |

## Required Before A Real End-To-End Demo

1. Provide authorized local acupuncture/tVNS PDF/Markdown samples and record
   parser success/failure statistics.
2. Provide usable MiMo base URL, model ID, and secret injection outside the
   repository; run and retain one real extraction result.
3. Have an expert attach expected citations or evidence sufficiency decisions to
   the seed questions, then measure retrieval recall and citation accuracy.
4. Perform a browser smoke test from a clean process using a real active release.
5. Provide a real external SourceConnector contract only if external-source sync
   is part of the demonstration.
6. Decide whether the one-process in-memory repositories are acceptable for the
   demonstration. A restart-persistent demo requires durable repository adapters
   and a seeded/resettable demo environment.

Until these gates are met, describe the deliverable as a deterministic fixture
demonstration of the V1 workflow, not a validated acupuncture evidence product.
