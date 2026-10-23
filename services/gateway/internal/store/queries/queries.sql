-- name: ListSymbols :many
SELECT symbol, name, exchange, is_etf FROM symbols ORDER BY symbol;

-- name: CountSymbols :one
SELECT COUNT(*) FROM symbols;

-- name: DeleteSymbols :exec
DELETE FROM symbols;

-- name: InsertSymbol :exec
INSERT INTO symbols (symbol, name, exchange, is_etf) VALUES (?, ?, ?, ?)
ON CONFLICT (symbol) DO UPDATE SET name = excluded.name, exchange = excluded.exchange, is_etf = excluded.is_etf;

-- name: GetKV :one
SELECT value, updated_at FROM kv WHERE key = ?;

-- name: SetKV :exec
INSERT INTO kv (key, value, updated_at) VALUES (?, ?, ?)
ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;

-- name: GetCache :one
SELECT value FROM market_cache WHERE key = ? AND expires_at > ?;

-- name: PutCache :exec
INSERT INTO market_cache (key, value, expires_at) VALUES (?, ?, ?)
ON CONFLICT (key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at;

-- name: PurgeCache :execrows
DELETE FROM market_cache WHERE expires_at <= ?;

-- name: InsertFeedback :one
INSERT INTO feedback (conversation_id, message_id, rating, reason, consent, transcript, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
RETURNING id;
