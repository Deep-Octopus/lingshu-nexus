# LingShu Nexus

LingShu Nexus is being built as an internal research evidence platform. V1 starts
with the `acupuncture` domain and keeps tVNS/taVNS as a first professional
sub-scenario, while avoiding patient-facing treatment advice and device control.

This repository currently contains the T-000 engineering scaffold plus the
T-010/T-030 foundations: versioned acupuncture/tVNS domain config, Evidence
Schema dataclasses, persistence records, SQL migrations, object storage and graph
repository ports, document upload/parsing services, quality commands, tests, and
ADRs.

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

- `POST /api/v1/domains/{domain_id}/documents:batch-upload`
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

## Worker

The worker entrypoint is a placeholder for future queue tasks:

```bash
make worker
```

Queue implementation and job models are deferred to later TODOs.

## Frontend

Install Web dependencies and start the Vite dev server:

```bash
npm --prefix frontend install
make web-dev
```

Open `http://localhost:5173`.

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

T-000 intentionally does not implement:

- MiMo provider calls
- graph database writes
- retrieval or GraphRAG
- Skill execution
- authentication or review workflows

Those are handled by later TODO items in
`项目TODO与Codex实现规则.md`.
