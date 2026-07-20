-- =============================================================================
-- 0001_init.sql  ·  NorthLight Desktop Telemetry & Clinician Dashboard
-- =============================================================================
-- PostgreSQL schema for the MVP slice. Four tables exactly (PRD §7):
--   users, telemetry_events, sessions, daily_metrics.
--
-- Design thesis (PRD §7.2): keep RAW events append-only and closest to the
-- device for correctness/recompute; serve pre-computed AGGREGATES to the
-- dashboard for speed and lower privacy exposure.
--
-- Privacy invariant enforced by the schema (PRD §1, §5): we store counts,
-- durations, app names, and switch counts -- NEVER content. There is no column
-- anywhere in this schema for keystrokes, characters, text, URLs, clipboard,
-- or screen contents. The absence of those columns is a deliberate, reviewable
-- part of the design: content cannot be persisted because there is nowhere to
-- put it.
--
-- Run:  psql "$DATABASE_URL" -f migrations/0001_init.sql
-- =============================================================================

-- gen_random_uuid() lives in the pgcrypto extension on PostgreSQL < 13.
-- On PG 13+ it is built in, but requiring the extension is harmless and makes
-- the migration portable across versions. IF NOT EXISTS keeps it idempotent.
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- -----------------------------------------------------------------------------
-- users  ·  the pseudonymous subject
-- -----------------------------------------------------------------------------
-- One row per monitored install. Deliberately holds NO name, email, phone,
-- device serial, IP, or any other direct identifier (PRD §2 privacy-first,
-- §11.4 de-identification).
--
-- `pseudonym` is a hash of a local install identifier produced on the device.
-- The raw identifier never leaves the machine; only its hash is sent and
-- stored here. This is the single key the rest of the schema references, so
-- the entire database is keyed on a pseudonym by construction -- there is no
-- code path that could attach a real identity.
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pseudonym   TEXT NOT NULL UNIQUE,           -- hashed local install id; never a name/email
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- -----------------------------------------------------------------------------
-- telemetry_events  ·  raw, append-only telemetry
-- -----------------------------------------------------------------------------
-- The high-volume, higher-exposure table. Every row is a single privacy-safe
-- observation the agent made: a bucketed input count, an app-focus change, a
-- lock/unlock, a sleep/wake. Kept append-only so metrics can be recomputed
-- from source when a formula changes, and so the pipeline can be debugged
-- (PRD §7.2). Shortest retention of any table (PRD §7.4): most sensitive data,
-- shortest life.
--
-- Column semantics:
--   event_type    Discriminator for the row. Application-level enum kept as
--                 TEXT for migration simplicity -- one of:
--                 'keyboard' | 'mouse' | 'app_focus' | 'lock' | 'unlock' |
--                 'sleep' | 'wake' | 'idle' | 'active'. A CHECK constraint is
--                 intentionally omitted so the agent can add signal types
--                 without a migration; the backend validates event_type on
--                 ingest (PRD §8.1) and rejects anything carrying unexpected
--                 content fields.
--   app_name      Foreground application name (e.g. "Safari"). NULL for
--                 non-app events. App name only -- coarse shape of the day.
--   window_title  Opt-in, treated as sensitive (PRD §5.4). NULL by default;
--                 the agent captures app name only unless a title is
--                 demonstrably non-sensitive. Present as a nullable column so
--                 the opt-in path exists, but the default data path leaves it
--                 NULL.
--   numeric_value A count (keystrokes, clicks, scrolls, switches) OR a
--                 duration in seconds, depending on event_type. One numeric
--                 column instead of many keeps the raw table thin; the meaning
--                 is fixed per event_type and documented at the aggregation
--                 layer.
--   ts            When the observation occurred, on the device clock, stored
--                 as TIMESTAMPTZ (UTC). Drives every time-range scan.
--
-- Note there is NO content column and NO free-text payload column. That is the
-- point: the only text columns are app_name and the opt-in window_title, both
-- bounded to application/window identity, never to what was typed or viewed.
-- -----------------------------------------------------------------------------
CREATE TABLE telemetry_events (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type    TEXT NOT NULL,                -- 'keyboard'|'mouse'|'app_focus'|'lock'|'unlock'|'sleep'|'wake'|'idle'|'active'
    app_name      TEXT,                         -- nullable; app-focus events only; app name, never content
    window_title  TEXT,                         -- nullable; opt-in, sensitive; NULL by default
    numeric_value NUMERIC,                       -- count OR duration-seconds, per event_type
    ts            TIMESTAMPTZ NOT NULL
);

-- Dominant access path: build a day's aggregates by scanning one user's events
-- within a time range (PRD §7.3). (user_id, ts) serves both the user filter
-- and the range/order in one index.
CREATE INDEX idx_telemetry_events_user_ts
    ON telemetry_events (user_id, ts);

-- Per-signal metric computation filters by event_type within a user's window
-- (e.g. sum keyboard counts, count app switches). The composite
-- (user_id, event_type, ts) covers those filtered range scans without touching
-- the heap for the ordering columns. Chosen over a bare (event_type) index
-- because every query is already scoped to a single user.
CREATE INDEX idx_telemetry_events_user_type_ts
    ON telemetry_events (user_id, event_type, ts);


-- -----------------------------------------------------------------------------
-- sessions  ·  derived active spans
-- -----------------------------------------------------------------------------
-- A session is an active span bounded by idle/lock/sleep transitions observed
-- in telemetry_events (PRD §7.1, §10.1). Derived, not raw: the backend opens a
-- session on wake/unlock/active and closes it on idle/lock/sleep. end_time and
-- duration_sec are NULL while a session is still open, then filled on close.
-- Sessions feed the "sustained session" component of the engagement/focus
-- scores and the activity timeline.
-- -----------------------------------------------------------------------------
CREATE TABLE sessions (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_time    TIMESTAMPTZ NOT NULL,
    end_time      TIMESTAMPTZ,                  -- NULL while the session is open
    duration_sec  INTEGER                       -- NULL until closed; filled from end_time - start_time
);

-- Sessions are read per user, ordered by when they started (timeline render,
-- daily rollup of session durations). (user_id, start_time) serves both.
CREATE INDEX idx_sessions_user_start
    ON sessions (user_id, start_time);


-- -----------------------------------------------------------------------------
-- daily_metrics  ·  one row per user per day (the aggregate the dashboard reads)
-- -----------------------------------------------------------------------------
-- Pre-computed per-day rollup (PRD §7.2, §8.3). The dashboard reads almost
-- exclusively from here: fast queries, and a day-summary reveals far less than
-- the underlying event stream, so it is the lower-exposure surface for wider
-- access. Longer retention than raw (PRD §7.4) -- it carries the trend value
-- with much lower re-identification risk.
--
-- focus_score / engagement_score are the transparent v1 heuristics (PRD §10),
-- stored as NUMERIC(5,2) on a 0-100 scale. NULLable so a day can exist as a
-- row before scores are computed. active/idle/switch counts default to 0 so a
-- freshly upserted day is well-formed before aggregation fills it in.
--
-- UNIQUE (user_id, date) enforces exactly one row per user-day and is the
-- conflict target for idempotent upserts (PRD §8.3): re-running aggregation
-- for a day overwrites rather than duplicates.
-- -----------------------------------------------------------------------------
CREATE TABLE daily_metrics (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date              DATE NOT NULL,
    active_minutes    INTEGER NOT NULL DEFAULT 0,
    idle_minutes      INTEGER NOT NULL DEFAULT 0,
    app_switch_count  INTEGER NOT NULL DEFAULT 0,
    focus_score       NUMERIC(5,2),             -- 0-100, transparent heuristic (PRD §10.2); NULL until computed
    engagement_score  NUMERIC(5,2),             -- 0-100, transparent heuristic (PRD §10.1); NULL until computed
    UNIQUE (user_id, date)
);

-- The UNIQUE (user_id, date) constraint above already creates a unique index
-- on (user_id, date), which is exactly the dashboard's retrieval key
-- (a user's days in order) and the upsert conflict target. No separate index
-- is needed -- adding one would duplicate the constraint's index (PRD §7.3).
