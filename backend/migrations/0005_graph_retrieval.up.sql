CREATE TABLE published_graph_nodes (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    node_key TEXT NOT NULL,
    label TEXT NOT NULL,
    properties_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (release_id) REFERENCES graph_releases (id),
    UNIQUE (domain_id, release_id, node_key)
);

CREATE TABLE published_graph_relationships (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    source_node_key TEXT NOT NULL,
    target_node_key TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    assertion_id TEXT NOT NULL,
    properties_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (release_id) REFERENCES graph_releases (id),
    FOREIGN KEY (assertion_id) REFERENCES evidence_assertions (id)
);

CREATE TABLE retrieval_index_entries (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    assertion_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    locator_json TEXT NOT NULL,
    index_text TEXT NOT NULL,
    review_status TEXT NOT NULL,
    source_quality_tier TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (release_id) REFERENCES graph_releases (id),
    FOREIGN KEY (assertion_id) REFERENCES evidence_assertions (id),
    FOREIGN KEY (document_id) REFERENCES source_documents (id),
    FOREIGN KEY (chunk_id) REFERENCES source_chunks (id)
);

CREATE INDEX idx_published_graph_nodes_release
    ON published_graph_nodes (domain_id, release_id, label);

CREATE INDEX idx_published_graph_relationships_release
    ON published_graph_relationships (domain_id, release_id, relationship_type);

CREATE INDEX idx_retrieval_index_entries_release
    ON retrieval_index_entries (domain_id, release_id, review_status);
