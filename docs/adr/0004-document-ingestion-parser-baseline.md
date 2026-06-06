# ADR 0004: Document Ingestion Parser Baseline

## Status

Accepted

## Context

T-030 needs a verifiable upload, raw storage, deduplication, and parsing path for
Markdown and PDF documents. The project should prefer mature parser components,
but the first real acupuncture/tVNS corpus and complex Chinese PDF samples are
not yet available. The implementation must not fabricate parser success on
unseen business documents.

## Decision

- Add a `DocumentParser` adapter boundary and keep parser-specific dependencies
  out of the ingestion service.
- Implement a deterministic Markdown parser in project code because heading and
  paragraph locator behavior is small, stable, and core to source citation.
- Use `pypdf` as the baseline PDF text-layer parser. It is a maintained pure
  Python PDF library, distributed under a BSD-style license, and can be replaced
  behind the parser adapter if Docling or MinerU performs better on the real
  corpus.
- Keep a minimal PDF text fallback only for offline fixture tests when `pypdf` is
  not installed. It is not treated as a production-grade parser.
- Add `python-multipart` for FastAPI file upload handling. It is the standard
  Starlette/FastAPI multipart parser dependency and is isolated to the API layer.
- Add `LocalFilesystemObjectStore` for local development so raw and parsed
  artifacts survive beyond a single service object. Production MinIO/S3 remains
  an object-store adapter concern.

## Consequences

- Markdown and simple text-layer PDF ingestion can be tested without external
  services.
- The API can expose upload, list, detail, and reprocess operations while
  preserving the raw/parsed artifact separation introduced in T-020.
- Complex PDF layout, scanned PDFs, tables, and OCR are not claimed complete.
  Docling should be evaluated first on the real validation corpus; MinerU remains
  a comparison candidate if Docling fails on Chinese medical layout examples.
- Parser dependency replacement does not affect Evidence Schema, review, release,
  or downstream extraction contracts.
