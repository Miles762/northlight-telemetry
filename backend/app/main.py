"""NorthLight backend -- exactly two endpoints (PRD §8).

    POST /events      ingest a batch of privacy-safe events, then recompute the
                      affected day(s)' daily_metrics on write.
    GET  /dashboard   read aggregates for the clinician dashboard.

No auth, no CRUD, no export endpoints -- those are [FUTURE] (PRD §8.4). All SQL
is parameterized (PRD §4 NFR).
"""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import aggregate
from .db import get_conn
from .models import EventsBatch, IngestResult

app = FastAPI(title="NorthLight Telemetry API", version="0.1.0")

# The dashboard runs on the Vite dev server (localhost:5173) and reads this API
# from the browser, so it needs CORS. Localhost only -- this never leaves the
# machine (PRD §4: single-machine slice).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _get_or_create_user(cur, pseudonym: str) -> str:
    """Return the users.id for a pseudonym, creating the row on first sight.

    The pseudonym is already a hash produced on the device (PRD §11.4); we never
    see the raw identifier. INSERT ... ON CONFLICT DO NOTHING keeps this
    idempotent under concurrent first-batches.
    """
    cur.execute(
        "INSERT INTO users (pseudonym) VALUES (%s) "
        "ON CONFLICT (pseudonym) DO NOTHING",
        (pseudonym,),
    )
    cur.execute("SELECT id FROM users WHERE pseudonym = %s", (pseudonym,))
    return cur.fetchone()["id"]


def _recompute_day(cur, user_id: str, day: date) -> None:
    """Recompute one day's derived sessions and daily_metrics from raw events.

    This is the on-write aggregation path (PRD §8.3): after inserting a batch we
    re-read that day's raw events and rebuild derived rows from scratch, so the
    result is identical whether events arrived in one batch or many. daily_metrics
    upserts on (user_id, date), and sessions are delete/reinsert for the day.
    """
    cur.execute(
        "SELECT event_type, app_name, numeric_value, ts "
        "FROM telemetry_events "
        "WHERE user_id = %s AND ts::date = %s "
        "ORDER BY ts",
        (user_id, day),
    )
    rows = cur.fetchall()
    m = aggregate.compute_daily_metrics(rows)
    sessions = aggregate.compute_sessions(rows)

    cur.execute(
        "DELETE FROM sessions WHERE user_id = %s AND start_time::date = %s",
        (user_id, day),
    )
    if sessions:
        cur.executemany(
            "INSERT INTO sessions (user_id, start_time, end_time, duration_sec) "
            "VALUES (%s, %s, %s, %s)",
            [
                (
                    user_id,
                    session["start_time"],
                    session["end_time"],
                    session["duration_sec"],
                )
                for session in sessions
            ],
        )

    cur.execute(
        """
        INSERT INTO daily_metrics
            (user_id, date, active_minutes, idle_minutes,
             app_switch_count, focus_score, engagement_score)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, date) DO UPDATE SET
            active_minutes   = EXCLUDED.active_minutes,
            idle_minutes     = EXCLUDED.idle_minutes,
            app_switch_count = EXCLUDED.app_switch_count,
            focus_score      = EXCLUDED.focus_score,
            engagement_score = EXCLUDED.engagement_score
        """,
        (
            user_id, day,
            m["active_minutes"], m["idle_minutes"], m["app_switch_count"],
            m["focus_score"], m["engagement_score"],
        ),
    )


# ---------------------------------------------------------------------------
# POST /events  -- ingestion + on-write aggregation
# ---------------------------------------------------------------------------

@app.post("/events", response_model=IngestResult)
def ingest_events(batch: EventsBatch) -> IngestResult:
    # Pydantic (models.py, extra="forbid") has already rejected any batch
    # carrying unexpected/content fields before we get here (PRD §8.1).
    if not batch.events:
        raise HTTPException(status_code=400, detail="empty batch")

    with get_conn() as conn, conn.cursor() as cur:
        user_id = _get_or_create_user(cur, batch.pseudonym)

        # Idempotency guard (PRD §4 NFR): if we have already ingested this
        # batch_id, do nothing and report zero new work. A retried POST is a
        # no-op -- raw rows are not appended twice and aggregates don't shift.
        cur.execute(
            "SELECT event_count FROM ingest_batches WHERE batch_id = %s",
            (str(batch.batch_id),),
        )
        seen = cur.fetchone()
        if seen:
            return IngestResult(
                inserted_events=0,
                days_aggregated=[],  # already aggregated on the original request
            )

        # Insert raw events. executemany keeps it one round-trip of statements;
        # every value is bound, never interpolated (parameterized SQL, §4).
        cur.executemany(
            "INSERT INTO telemetry_events "
            "(user_id, event_type, app_name, numeric_value, ts) "
            "VALUES (%s, %s, %s, %s, %s)",
            [
                (
                    user_id, e.event_type, e.app_name, e.numeric_value, e.ts,
                )
                for e in batch.events
            ],
        )

        # Record the batch id so a retry is recognized and skipped. Same
        # transaction as the raw insert: either both land or neither does, so
        # the ledger never claims a batch we didn't actually store.
        cur.execute(
            "INSERT INTO ingest_batches (batch_id, user_id, event_count) "
            "VALUES (%s, %s, %s)",
            (str(batch.batch_id), user_id, len(batch.events)),
        )

        # Recompute only the day(s) this batch touched (on-write aggregation).
        days = sorted(aggregate.days_touched([e.model_dump() for e in batch.events]))
        for day in days:
            _recompute_day(cur, user_id, day)

    return IngestResult(
        inserted_events=len(batch.events),
        days_aggregated=[d.isoformat() for d in days],
    )


# ---------------------------------------------------------------------------
# GET /dashboard  -- read aggregates
# ---------------------------------------------------------------------------

@app.get("/dashboard")
def get_dashboard(pseudonym: str | None = None) -> dict:
    """Return the aggregates the clinician dashboard renders (PRD §8.2, §9).

    Reads daily_metrics for summary/trends and latest-day raw, content-free rows
    for app usage and timeline markers. For the single-user slice, pseudonym is
    optional -- if omitted we return the
    most recently active user. Shape:
        {
          "pseudonym": str,
          "daily_metrics": [ {date, active_minutes, idle_minutes,
                              app_switch_count, focus_score, engagement_score}, ...],
          "summary":  <latest day's row or null>,
          "app_usage": [ {app_name, minutes} ],   # latest day, app-name only
          "timeline":  [ {event_type, clock, seconds} ],  # latest day, intraday
          "baseline": {trailing_mean_active, delta_active_pct, confidence, ...}
        }
    """
    with get_conn() as conn, conn.cursor() as cur:
        # Resolve which user we are showing.
        if pseudonym:
            cur.execute("SELECT id, pseudonym FROM users WHERE pseudonym = %s", (pseudonym,))
        else:
            cur.execute(
                "SELECT u.id, u.pseudonym FROM users u "
                "JOIN daily_metrics d ON d.user_id = u.id "
                "ORDER BY d.date DESC LIMIT 1"
            )
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="no data for user")
        user_id = user["id"]

        # Daily metrics series (the trend), oldest -> newest.
        cur.execute(
            "SELECT date, active_minutes, idle_minutes, app_switch_count, "
            "       focus_score, engagement_score "
            "FROM daily_metrics WHERE user_id = %s ORDER BY date",
            (user_id,),
        )
        daily = cur.fetchall()
        for row in daily:
            row["date"] = row["date"].isoformat()
            # NUMERIC comes back as Decimal; make it JSON-friendly.
            row["focus_score"] = _f(row["focus_score"])
            row["engagement_score"] = _f(row["engagement_score"])

        summary = daily[-1] if daily else None

        # App usage for the latest day: time-in-focus per app (app NAME only --
        # no titles, no URLs). Derived from raw app_focus events (PRD §9.2).
        app_usage = []
        if summary:
            cur.execute(
                "SELECT app_name, "
                "       ROUND(SUM(COALESCE(numeric_value,0))/60.0, 1) AS minutes "
                "FROM telemetry_events "
                "WHERE user_id = %s AND event_type = 'app_focus' "
                "      AND ts::date = %s AND app_name IS NOT NULL "
                "GROUP BY app_name ORDER BY minutes DESC",
                (user_id, summary["date"]),
            )
            app_usage = [{"app_name": r["app_name"], "minutes": _f(r["minutes"])}
                         for r in cur.fetchall()]

        # Intraday timeline for the latest day (PRD §9.2): the raw session-shape
        # events across the day -- active/idle spans, lock/sleep/wake/unlock
        # transitions, and coarse system-state markers -- so the dashboard can draw
        # the day's rhythm. Still no content: each row is a type, a timestamp, and
        # a controlled number.
        timeline = []
        if summary:
            cur.execute(
                "SELECT event_type, "
                "       to_char(ts, 'HH24:MI') AS clock, "
                "       COALESCE(numeric_value, 0) AS seconds "
                "FROM telemetry_events "
                "WHERE user_id = %s AND ts::date = %s "
                "      AND event_type IN "
                "          ('active','idle','lock','unlock','sleep','wake', "
                "           'power_ac','battery_percent','network_connected', "
                "           'display_count') "
                "ORDER BY ts",
                (user_id, summary["date"]),
            )
            timeline = [
                {"event_type": r["event_type"], "clock": r["clock"],
                 "seconds": _f(r["seconds"])}
                for r in cur.fetchall()
            ]

        # Baseline comparison (PRD §9.3, §10.3): latest day's active minutes vs
        # the trailing mean of prior days -- relative to the person's OWN norm,
        # never a population norm.
        baseline = aggregate.compute_baseline(daily)

    return {
        "pseudonym": user["pseudonym"],
        "daily_metrics": daily,
        "summary": summary,
        "app_usage": app_usage,
        "timeline": timeline,
        "baseline": baseline,
    }


def _f(v):
    """Decimal/None -> float/None for JSON serialization."""
    return float(v) if v is not None else None
