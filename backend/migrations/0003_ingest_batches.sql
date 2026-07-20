-- =============================================================================
-- 0003_ingest_batches.sql  ·  Idempotent ingestion ledger (PRD §4 NFR)
-- =============================================================================
-- PRD §4 requires ingestion to be "idempotent-friendly (batch + event identity)
-- so a retried POST doesn't double-count." The daily_metrics upsert already
-- makes AGGREGATION idempotent; this table makes RAW INSERTION idempotent too.
--
-- The agent assigns each batch a UUID (batch_id) before its first send attempt
-- and reuses it on retries. We record every batch_id we have fully ingested;
-- if the same batch_id arrives again we skip the insert entirely. That is the
-- "batch identity" half of the NFR -- one row per batch, not per event, which
-- is enough because the agent sends a batch atomically.
--
-- No content here either: this table records only that a batch (by opaque id)
-- was seen, for which pseudonymous user, and when.
-- =============================================================================

CREATE TABLE ingest_batches (
    batch_id     UUID PRIMARY KEY,               -- client-generated; the dedup key
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_count  INTEGER NOT NULL,               -- how many events this batch carried
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Look up a user's ingested batches (operational/debug); the PK already covers
-- the hot path (has this exact batch_id been seen?), so this is the only extra.
CREATE INDEX idx_ingest_batches_user ON ingest_batches (user_id);
