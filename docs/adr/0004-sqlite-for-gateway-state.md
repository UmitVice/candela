# 0004 — SQLite for gateway state

- Status: accepted
- Date: 2026-10-23

## Context

The gateway runs as a single instance on free hosting with an ephemeral disk. Its state is small: the symbol directory, a market response cache, feedback records, and a read-only price snapshot. A managed PostgreSQL would need an extra account and network hop for no functional gain.

## Decision

Use SQLite through the pure-Go `modernc.org/sqlite` driver (no CGO, static binary), WAL mode, goose migrations embedded in the binary and sqlc-generated queries. The market snapshot is a separate read-only SQLite file built offline. Feedback that must outlive the container is exported to a Hugging Face dataset by the deploy tooling.

## Consequences

- Zero operational dependencies; identical behaviour locally and in the Space.
- Single-writer semantics are fine at this scale; horizontal scaling would need a shared store (PostgreSQL with pgvector is the planned path and sqlc supports both).

## Alternatives considered

- PostgreSQL 17 + pgvector: already installed locally and the natural choice for multi-instance or vector search; deferred until retrieval or scale requires it.
- Pure in-memory state: loses feedback on every restart.
