-- +goose Up
CREATE TABLE symbols (
    symbol     TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    exchange   TEXT NOT NULL,
    is_etf     INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;

CREATE TABLE kv (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE market_cache (
    key        TEXT PRIMARY KEY,
    value      BLOB NOT NULL,
    expires_at INTEGER NOT NULL
) WITHOUT ROWID;

CREATE INDEX market_cache_expires ON market_cache (expires_at);

CREATE TABLE feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    rating          INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    reason          TEXT,
    consent         INTEGER NOT NULL,
    transcript      TEXT,
    created_at      INTEGER NOT NULL
);

CREATE INDEX feedback_conversation ON feedback (conversation_id);

-- +goose Down
DROP TABLE feedback;
DROP TABLE market_cache;
DROP TABLE kv;
DROP TABLE symbols;
