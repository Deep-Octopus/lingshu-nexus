CREATE TABLE chat_sessions (
    id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    domain_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    skill_id TEXT,
    skill_version TEXT,
    release_id TEXT,
    release_version TEXT,
    citation_keys_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions (id),
    FOREIGN KEY (release_id) REFERENCES graph_releases (id)
);

CREATE TABLE chat_feedback (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    domain_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    rating TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions (id),
    FOREIGN KEY (message_id) REFERENCES chat_messages (id)
);

CREATE INDEX idx_chat_sessions_domain
    ON chat_sessions (domain_id, created_at);

CREATE INDEX idx_chat_messages_session
    ON chat_messages (domain_id, session_id, created_at);

CREATE INDEX idx_chat_feedback_message
    ON chat_feedback (domain_id, message_id, created_at);
