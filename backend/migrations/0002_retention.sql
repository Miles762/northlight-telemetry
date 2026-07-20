-- =============================================================================
-- 0002_retention.sql  ·  Retention policy (PRD §7.4)
-- =============================================================================
-- Retention length tracks sensitivity INVERSELY: the more granular and
-- re-identifiable the data, the sooner it expires.
--
--   Raw events (telemetry_events):  30-90 days.  Highest exposure, shortest
--     life. Long enough to establish a baseline and recompute metrics after a
--     formula change; short enough to bound standing privacy risk. We pin the
--     MVP horizon at 90 days.
--   Aggregated metrics (daily_metrics) and derived sessions:  longer (1-2 yrs).
--     They carry the clinical trend value with far lower re-identification
--     risk, so they justify a longer horizon.
--
-- SCOPE NOTE: automated scheduled deletion (a cron/pg_cron job, background
-- worker, or infra scheduler) is [FUTURE] operational surface and is NOT built
-- in the slice (PRD §2.2, §8.4). What lives here is the policy as an executable
-- function a reviewer can read and run by hand, so the retention decision is
-- concrete and testable rather than prose-only. Nothing calls it automatically.
-- =============================================================================

-- Delete raw events older than the retention horizon. Aggregates and sessions
-- are intentionally left untouched -- they outlive the raw stream. Parameterized
-- on the cutoff-in-days so the horizon (30-90) is explicit at the call site.
--
-- Run manually, e.g. enforce the 90-day raw horizon:
--   SELECT enforce_raw_retention(90);
CREATE OR REPLACE FUNCTION enforce_raw_retention(retain_days INTEGER)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    deleted BIGINT;
BEGIN
    DELETE FROM telemetry_events
    WHERE ts < now() - make_interval(days => retain_days);
    GET DIAGNOSTICS deleted = ROW_COUNT;
    RETURN deleted;   -- number of raw rows expired, for the caller to log
END;
$$;
