# LingShu Nexus

LingShu Nexus is being built as an internal research evidence platform. V1 starts
with the `acupuncture` domain and keeps tVNS/taVNS as a first professional
sub-scenario, while avoiding patient-facing treatment advice and device control.

This repository currently contains the T-000 engineering scaffold plus the
T-010/T-100 foundations: versioned acupuncture/tVNS domain config, Evidence
Schema dataclasses, persistence records, SQL migrations, object storage and graph
repository ports, document upload/parsing services, candidate extraction
services, review/release governance, published graph retrieval, Agent Skill
Registry baseline, SSE evidence chat, management panel baseline, SourceConnector
incremental update baseline, quality commands, tests, and ADRs.

## Prerequisites

- Python 3.12+
- `uv`
- Node.js 22+ and npm
- Docker or another Compose-compatible runtime

## Configuration

Copy the template and replace placeholders for real local use:

```bash
cp .env.example .env
```

Do not commit real API keys, database passwords, object-storage credentials, or
Neo4j credentials. The committed template only contains placeholders.

## Local Infrastructure

Start the local dependency services:

```bash
docker compose up -d postgres redis minio neo4j
```

Services:

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- MinIO API: `localhost:9000`, console: `localhost:9001`
- Neo4j browser: `localhost:7474`, Bolt: `localhost:7687`

## Backend API

Install Python dependencies:

```bash
uv sync --extra dev
```

Start the API:

```bash
make api
```

Health check:

```bash
curl http://localhost:8000/healthz
```

Expected response includes `status: ok` and `default_domain_id: acupuncture`.

### Document Ingestion API

T-030 adds synchronous PDF/Markdown ingestion endpoints for the internal research
workflow:

- `POST /api/v1/domains/{domain_id}/documents/batch-upload`
- `GET /api/v1/documents?domain_id=acupuncture`
- `GET /api/v1/documents/{document_id}?domain_id=acupuncture`
- `POST /api/v1/documents/{document_id}:reprocess?domain_id=acupuncture`

Uploads are content-hashed before storage. Duplicate bytes in the same
`domain_id` return the existing document record instead of creating another
formal document. Raw uploads and parsed chunk JSON are written through the
object-store port; local API runs use `OBJECT_STORAGE_LOCAL_PATH`, which defaults
to `data/runtime/object-store`.

Markdown parsing is deterministic and produces heading/paragraph locators. PDF
parsing is behind the `DocumentParser` adapter and uses `pypdf` as the baseline
text-layer parser; complex layout/OCR evaluation with real Chinese samples is
deferred until the first corpus is available.

### Candidate Extraction

T-040 adds an `EvidenceExtractor` service that reads parsed chunks and writes
candidate-layer outputs only. It does not approve, publish, or write graph data.

The default live provider adapter is MiMo, configured only through environment
variables:

- `MIMO_API_KEY`
- `MIMO_BASE_URL`
- `MIMO_MODEL_ID`
- `MIMO_EXTRACTION_MODEL_ID` optional; falls back to `MIMO_MODEL_ID`

Unit and integration tests use `FakeLlmProvider`, so no real key is required for
offline validation. Live MiMo extraction is intentionally blocked until real
provider settings are supplied.

### Incremental Updates and SourceConnector

T-100 adds a controlled `SourceConnector` path for new material:

- `GET /api/v1/sources?domain_id=acupuncture`
- `POST /api/v1/sources?domain_id=acupuncture`
- `POST /api/v1/sources/{source_id}:sync?domain_id=acupuncture`
- `GET /api/v1/source-runs?domain_id=acupuncture`
- `GET /api/v1/source-runs/{run_id}?domain_id=acupuncture`
- `POST /api/v1/source-runs/{run_id}:retry?domain_id=acupuncture`
- `POST /api/v1/domains/{domain_id}/sources:manual-sync`

`SourceArtifact` is the internal contract for external input and supports JSON
payloads, file payloads, and download references. Every artifact is stored in the
raw layer first. File and explicit internal JSON document payloads then enter the
existing document parser, candidate extraction, and review-batch workflow.
Duplicate artifact idempotency keys and duplicate document hashes are skipped, so
repeat syncs do not create duplicate candidate batches.

The built-in fixture connector verifies JSON/file/download-reference handling
without network access. The generic REST connector preserves raw responses and
maps only explicit `SourceArtifact` shapes; it does not guess PubMed, Crossref,
CNKI, or other external schemas before real request/response samples and
authorization rules are supplied. Connector configs reject inline secret-looking
keys such as API keys, tokens, passwords, and secrets; use secret references in a
future durable config store instead.

### Agent Skill Registry

T-070 adds a read-only Agent Skill Registry baseline:

- `GET /api/v1/skills?domain_id=acupuncture`
- `GET /api/v1/skills/{skill_id}?domain_id=acupuncture`
- `POST /api/v1/skills/{skill_id}:validate?domain_id=acupuncture`
- `POST /api/v1/skills/{skill_id}:enable|disable?domain_id=acupuncture`
- `POST /api/v1/domains/{domain_id}/skills:execute`
- `GET /api/v1/domains/{domain_id}/skills/execution-logs`

Built-in Skill packages live under `skills/` and are loaded from
`SKILL_REGISTRY_PATH`, which defaults to `skills`. The first two enabled Skills
are `evidence-query` and `literature-landscape`. Platform authorization is
enforced from `registry.yaml` metadata, not from prompt text. Chat execution only
permits active `read_only` Skills over the active published release and records
Skill version, route mode, release version, and citation keys in execution logs.

### Evidence Chat

T-080 adds a web-ready chat baseline backed by Server-Sent Events:

- `POST /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions?domain_id=acupuncture`
- `GET /api/v1/chat/sessions/{session_id}/messages?domain_id=acupuncture`
- `POST /api/v1/chat/sessions/{session_id}/messages:stream?domain_id=acupuncture`
- `POST /api/v1/chat/sessions/{session_id}/messages/{message_id}:feedback?domain_id=acupuncture`

The stream emits `retrieval`, `text`, `citation`, `done`, and `error` events.
It reuses the read-only Skill Registry path, so chat can only answer from the
indexed active release and cannot read candidate extraction output. The Vue app
now opens directly to the evidence chat workspace with Skill selection, streamed
answer text, citation cards, active release metadata, clear no-release/no-evidence
states, and useful/not useful/correction feedback.

### Management Panel API

T-090 adds management endpoints and a Vue console for the P0 operating loop:

- `GET /api/v1/admin/overview?domain_id=acupuncture`
- `GET /api/v1/admin/jobs?domain_id=acupuncture`
- `GET /api/v1/admin/audit-events?domain_id=acupuncture`
- `POST /api/v1/admin/skills:upload`
- `POST /api/v1/admin/skills/{skill_id}:enable|disable?domain_id=acupuncture`

The console can upload and inspect documents, view parsed chunks and failed
parse jobs, operate review decisions, preview/create/activate/rollback graph
releases, upload/validate/enable/disable/run read-only Skill packages, inspect
Skill logs, run SourceConnector syncs, inspect source runs, and verify published
evidence through the chat view. Release and Skill management actions use
confirmation prompts in the UI and write audit events through the server-side
audit model.

The overview reports model usage as unavailable when no model usage repository
is mounted. It does not fabricate token or cost values. SourceConnector schedule
metadata and offline/generic execution are present; true external adapters remain
blocked until real interface samples are available.

## Worker

The worker entrypoint is a placeholder for future queue tasks:

```bash
make worker
```

Queue implementation and job models are deferred to later TODOs.

## Frontend

Install Web dependencies, start the API in one terminal, then start the Vite dev
server in another terminal:

```bash
npm --prefix frontend install
make api
```

```bash
make web-dev
```

Open `http://localhost:5173`. The first screen is the management console, with a
Chat tab for active-release answer verification. In local development, Vite
proxies `/api/v1` to `http://127.0.0.1:8000`, so the frontend can call the API
without setting `VITE_API_BASE_URL`. If the API runs on a different port, start
the frontend with `VITE_API_PROXY_TARGET=http://127.0.0.1:<port> make web-dev`,
or set `VITE_API_BASE_URL` to the full API base URL.

## Quality Commands

These commands are the T-000 baseline and can run before project dependencies are
installed:

```bash
make lint
make format-check
make typecheck
make test
```

`make quality` runs all four. When Ruff or Mypy are installed, the quality script
delegates to them; otherwise it runs deterministic standard-library fallback
checks that validate syntax, text formatting, config placeholders, and package
structure.

## Scope Notes

Authentication, persistent production repositories, full RBAC enforcement, and
observability hardening are handled by later TODO items in
`项目TODO与Codex实现规则.md`.
