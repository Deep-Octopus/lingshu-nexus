CREATE TABLE document_ingest_records (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    source_document_id TEXT,
    original_filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_object_uri TEXT,
    parsed_object_uri TEXT,
    parser_version TEXT,
    failure_reason TEXT,
    parse_attempts INTEGER NOT NULL DEFAULT 0 CHECK (parse_attempts >= 0),
    status_history_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_document_id) REFERENCES source_documents (id),
    UNIQUE (domain_id, content_hash)
);

CREATE INDEX idx_document_ingest_records_domain_status
    ON document_ingest_records (domain_id, status);
