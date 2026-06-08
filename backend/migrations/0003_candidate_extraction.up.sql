CREATE TABLE candidate_extraction_runs (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    status TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    source_chunk_ids_json TEXT NOT NULL,
    token_usage_json TEXT NOT NULL DEFAULT '{}',
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    raw_response_hash TEXT,
    output_object_uri TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES source_documents (id)
);

CREATE TABLE candidate_evidence_assertions (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    extraction_run_id TEXT NOT NULL,
    assertion_json TEXT NOT NULL,
    source_chunk_ids_json TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (extraction_run_id) REFERENCES candidate_extraction_runs (id)
);

CREATE INDEX idx_candidate_extraction_runs_document
    ON candidate_extraction_runs (domain_id, document_id, created_at);

CREATE INDEX idx_candidate_evidence_assertions_run
    ON candidate_evidence_assertions (domain_id, extraction_run_id);
