"""Daily aggregation and the transparent v1 scores (PRD §10).

This module turns a day's raw telemetry_events into one daily_metrics row. It is
deliberately the most heavily-commented file in the backend: the focus and
engagement scores are hand-set heuristics, and the whole point (PRD §10, §13) is
that a clinician or reviewer can trace every number back to the raw signal.

Everything here is pure arithmetic on counts and durations. No content is read
because none exists in the data.

--------------------------------------------------------------------------------
SCORE DEFINITIONS (0-100, higher = more focused / more engaged)

Focus score -- weighted heuristic exactly per PRD §10.2:
    40%  active time        -- fraction of a nominal working day spent active
    30%  sustained app use  -- mean focus-span length before switching apps
    20%  low app switching  -- inverse of switch frequency (less fragmentation)
    10%  consistency        -- how evenly activity was spread across the day

Engagement score -- per PRD §10.1 ("showed up, stayed, and did so consistently"):
    50%  active time        -- how much of the day was active
    30%  session duration   -- presence of sustained sessions, not just fleeting
    20%  consistent activity -- spread across the day vs a single burst
(The engagement weights are not fixed by the PRD the way Focus's are; these are
the simplest defensible split of the three named components and are documented
here and in NOTES.md.)

All component sub-scores are normalized to 0..1 against transparent reference
constants defined below, then weighted and scaled to 0..100. The constants are
v1 guesses; §10 explicitly calls future calibration [FUTURE].
--------------------------------------------------------------------------------
"""

from __future__ import annotations

from datetime import date, datetime, timezone

# --- Reference constants (v1, transparent, calibration is [FUTURE] per §10) ---

# A "full" active day for normalization. 6h of active computer use maps active
# time to 1.0; more is clamped. Not a clinical target -- just the scale anchor.
FULL_ACTIVE_MINUTES = 6 * 60

# Sustained-use anchor: a mean focus span of this many seconds before switching
# apps counts as fully sustained (1.0). ~5 min of unbroken focus = good.
SUSTAINED_FOCUS_SECONDS = 5 * 60

# Switching anchor: at/above this many app switches per active hour, the
# "low switching" sub-score bottoms out at 0. Below it, score scales linearly up.
SWITCHES_PER_HOUR_CEILING = 30

# Consistency is measured over the waking window as coverage across hour-buckets:
# activity touching this many distinct hours of the day = fully consistent (1.0).
CONSISTENT_HOURS_TARGET = 8

# Idle gap (seconds) that closes a session. Matches the agent's idle threshold;
# used when deriving sessions from active/idle/lock/sleep transitions.
SESSION_IDLE_GAP_SECONDS = 5 * 60


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _num(v) -> float:
    """Coerce a row's numeric_value to float.

    The telemetry_events.numeric_value column is Postgres NUMERIC, which psycopg
    returns as decimal.Decimal. All the score math below is in float, and Python
    refuses to multiply float * Decimal. Normalizing to float here -- at the one
    boundary where DB values enter the arithmetic -- keeps every downstream
    computation in a single numeric type. NULL -> 0.0.
    """
    return float(v) if v is not None else 0.0


def _local_day(ts: datetime) -> date:
    """The calendar day an event belongs to.

    Events arrive as TIMESTAMPTZ (UTC). For the MVP we bucket by UTC date; a
    real deployment would bucket by the patient's local timezone. Noted as a
    simplification in NOTES.md rather than invented here.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).date()


def compute_daily_metrics(events: list[dict]) -> dict:
    """Compute one daily_metrics row's fields from a single day's events.

    `events` is a list of rows (dicts) for ONE user on ONE day, each with keys:
    event_type, app_name, numeric_value, ts. Returns the metric fields; the
    caller upserts them. Kept pure (no DB) so it is trivially unit-testable and
    re-runnable when a formula changes -- the reason we keep raw events at all.
    """
    # --- 1. Active vs idle minutes -------------------------------------------
    # Active minutes: sum of durations from 'active'/'unlock'/'wake' spans is
    # complex to reconstruct here, so we use the simple, defensible proxy the
    # agent already gives us -- 'active' events carry the active-span seconds in
    # numeric_value, 'idle' events carry the idle-span seconds. We sum each.
    active_seconds = sum(
        _num(e["numeric_value"]) for e in events if e["event_type"] == "active"
    )
    idle_seconds = sum(
        _num(e["numeric_value"]) for e in events if e["event_type"] == "idle"
    )
    active_minutes = int(round(active_seconds / 60))
    idle_minutes = int(round(idle_seconds / 60))

    # --- 2. App switches & sustained focus spans -----------------------------
    # App-switch count comes from dedicated 'app_switch' events, which carry the
    # number of REAL foreground-app changes the agent observed in a bucket. We must
    # NOT infer switches from the number of 'app_focus' rows: the agent re-emits the
    # open app's running span as an app_focus event every bucket to keep duration
    # totals accurate, so len(app_focus) counts buckets-of-focus, not switches, and
    # would badly inflate the attention-fragmentation signal for a user who stays in
    # one app.
    app_switch_count = int(sum(
        _num(e["numeric_value"]) for e in events if e["event_type"] == "app_switch"
    ))

    # 'app_focus' events carry per-app focus DURATION (seconds); we use their
    # durations for the sustained-use sub-score.
    focus_events = [e for e in events if e["event_type"] == "app_focus"]
    focus_durations = [_num(e["numeric_value"]) for e in focus_events]
    mean_focus_span = (
        sum(focus_durations) / len(focus_durations) if focus_durations else 0.0
    )

    # --- 3. Component sub-scores (each 0..1) ---------------------------------
    # 3a. Active-time sub-score: active minutes vs a full active day.
    s_active = _clamp01(active_minutes / FULL_ACTIVE_MINUTES)

    # 3b. Sustained-use sub-score: mean unbroken focus span vs the anchor.
    s_sustained = _clamp01(mean_focus_span / SUSTAINED_FOCUS_SECONDS)

    # 3c. Low-switching sub-score: fewer switches per active hour = higher.
    active_hours = max(active_minutes / 60, 1e-9)  # avoid /0; tiny floor
    switches_per_hour = app_switch_count / active_hours
    s_low_switch = _clamp01(1.0 - switches_per_hour / SWITCHES_PER_HOUR_CEILING)

    # 3d. Consistency sub-score: how many distinct hours-of-day saw activity.
    active_hours_of_day = {
        _hour_of(e["ts"]) for e in events
        if e["event_type"] in ("keyboard", "mouse", "active", "app_focus")
    }
    s_consistency = _clamp01(len(active_hours_of_day) / CONSISTENT_HOURS_TARGET)

    # 3e. Session-duration sub-score (for engagement): reuse mean focus span as a
    # proxy for "sustained sessions" -- longer typical spans => more sustained.
    s_session = s_sustained

    # --- 4. Weighted scores (0..100) ----------------------------------------
    # Focus: 40 active / 30 sustained / 20 low-switch / 10 consistency (§10.2).
    focus_score = 100.0 * (
        0.40 * s_active
        + 0.30 * s_sustained
        + 0.20 * s_low_switch
        + 0.10 * s_consistency
    )

    # Engagement: 50 active / 30 session-duration / 20 consistency (§10.1).
    engagement_score = 100.0 * (
        0.50 * s_active
        + 0.30 * s_session
        + 0.20 * s_consistency
    )

    return {
        "active_minutes": active_minutes,
        "idle_minutes": idle_minutes,
        "app_switch_count": app_switch_count,
        "focus_score": round(focus_score, 2),
        "engagement_score": round(engagement_score, 2),
    }


def _hour_of(ts) -> int:
    """Hour-of-day (0-23, UTC) for consistency bucketing. Accepts datetime."""
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).hour


def days_touched(events: list[dict]) -> set[date]:
    """The set of calendar days any event in the batch falls on."""
    return {_local_day(e["ts"]) for e in events}
