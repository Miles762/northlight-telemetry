#!/usr/bin/env python3
"""Synthetic telemetry generator (PRD §8.5) — CLEARLY LABELED, NOT REAL DATA.

============================================================================
 REAL captured telemetry from the Swift agent is the source of truth and the
 main demo path. This generator exists for ONE reason: trend and baseline
 charts need several days of history, and a half-day exercise doesn't produce
 that. It backfills extra days so §9.3 baseline / §9.2 trend logic can be
 exercised. It NEVER replaces real capture.
============================================================================

How it stays honest and un-confusable with real data:
  * Every synthetic subject's pseudonym starts with "synthetic-". That prefix
    is visible in the DB and shows up on the dashboard's subject label, so a
    reviewer can always tell synthetic days from real ones at a glance.
  * It POSTs through the SAME `POST /events` endpoint the real agent uses —
    no privileged direct-insert path, no bypassing validation. Generating data
    therefore also exercises the real ingestion + aggregation pipeline.
  * It emits only the same privacy-safe shapes the agent emits: counts,
    durations, app names. No content, ever (there is nowhere to put any).

Usage:
  python synthetic.py generate               # 14 days into synthetic-demo-001
  python synthetic.py generate --days 30 --pseudonym synthetic-demo-002
  python synthetic.py reset                  # delete ALL synthetic-* subjects
  python synthetic.py reset --pseudonym synthetic-demo-002   # just one

Env:
  BACKEND_URL   default http://127.0.0.1:8000   (generate posts here)
  DATABASE_URL  default postgresql://postgres:postgres@localhost:5432/northlight
                (reset deletes here — parameterized SQL only)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

# Synthetic subjects are ALWAYS named with this prefix. Do not remove it — it is
# the label that keeps synthetic data distinguishable from real capture.
SYNTHETIC_PREFIX = "synthetic-"
DEFAULT_PSEUDONYM = "synthetic-demo-001"

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/northlight",
)

# A small, realistic set of app names (names only — never titles/URLs).
APPS = ["VS Code", "Safari", "Slack", "Mail", "Terminal", "Notes", "Zoom"]


def _post_batch(pseudonym: str, events: list[dict]) -> None:
    """POST one batch through the real /events endpoint (same path as the agent)."""
    body = json.dumps(
        {"batch_id": str(uuid.uuid4()), "pseudonym": pseudonym, "events": events}
    ).encode()
    req = urllib.request.Request(
        f"{BACKEND_URL}/events", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        json.loads(resp.read().decode())  # raises on non-2xx


def _one_day(day_start: datetime, low_activity: bool) -> list[dict]:
    """Build one realistic day of privacy-safe events.

    Produces the same event shapes the agent emits: an active span, an idle
    span, unlock/lock boundaries, per-app focus spans (name + duration), and
    keyboard/mouse counts. `low_activity` days deliberately dip so the baseline
    "worth a look" path (§9.3) has something to flag.
    """
    active_hours = random.uniform(1.0, 1.6) if low_activity else random.uniform(3.5, 5.5)
    idle_seconds = random.uniform(1200, 3000) if low_activity else random.uniform(600, 2400)

    events: list[dict] = []
    events.append({"event_type": "unlock", "ts": day_start.isoformat(), "numeric_value": None})
    events.append({"event_type": "active", "ts": day_start.isoformat(),
                   "numeric_value": round(active_hours * 3600, 1)})

    # App-focus spans spread across the active window. Fewer switches on a low
    # day (less fragmentation to observe), more on a busy day.
    n_switch = random.randint(3, 5) if low_activity else random.randint(10, 22)
    t = day_start
    for _ in range(n_switch):
        span = random.uniform(120, 900)
        events.append({"event_type": "app_focus", "ts": t.isoformat(),
                       "numeric_value": round(span, 1), "app_name": random.choice(APPS)})
        t += timedelta(seconds=span)
    # Switch COUNT as its own signal, matching what the real agent emits (a dedicated
    # app_switch event), rather than relying on len(app_focus). This keeps synthetic
    # data faithful to the real pipeline so the switch/fragmentation path is exercised
    # the same way for real and synthetic days.
    events.append({"event_type": "app_switch", "ts": day_start.isoformat(),
                   "numeric_value": n_switch})

    # Input COUNTS only — never keys/characters (mirrors the agent's counters).
    events.append({"event_type": "keyboard", "ts": day_start.isoformat(),
                   "numeric_value": random.randint(150, 900)})
    events.append({"event_type": "mouse", "ts": day_start.isoformat(),
                   "numeric_value": random.randint(80, 400)})

    end = day_start + timedelta(hours=active_hours)
    events.append({"event_type": "idle", "ts": end.isoformat(),
                   "numeric_value": round(idle_seconds, 1)})
    events.append({"event_type": "lock", "ts": end.isoformat(), "numeric_value": None})
    return events


def generate(pseudonym: str, days: int) -> None:
    if not pseudonym.startswith(SYNTHETIC_PREFIX):
        raise SystemExit(
            f"refusing: synthetic pseudonym must start with '{SYNTHETIC_PREFIX}' "
            f"(got '{pseudonym}') — the prefix is the label that keeps synthetic "
            f"data distinguishable from real capture."
        )
    # Backfill ending YESTERDAY (UTC), so synthetic days sit behind any real day
    # captured today and the most recent real data stays the visible "latest".
    today = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    for i in range(days, 0, -1):
        day_start = today - timedelta(days=i)
        # Roughly 1 in 7 days is a low-activity dip to exercise the baseline flag.
        low = (i % 7 == 3)
        _post_batch(pseudonym, _one_day(day_start, low_activity=low))
    print(f"[SYNTHETIC] generated {days} day(s) for '{pseudonym}' via {BACKEND_URL}/events")
    print("[SYNTHETIC] this is DEMO data, clearly labeled by the 'synthetic-' pseudonym prefix.")


def reset(pseudonym: str | None) -> None:
    """Delete synthetic subjects and their data. Parameterized SQL only.

    There is deliberately no delete ENDPOINT (the backend is two endpoints by
    design, §8.4), so reset talks to the DB directly. ON DELETE CASCADE on the
    child tables means removing the users row clears events/sessions/metrics/
    batches for that subject.
    """
    import psycopg  # imported here so `generate` needs no DB driver

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        if pseudonym:
            cur.execute("DELETE FROM users WHERE pseudonym = %s", (pseudonym,))
            scope = f"'{pseudonym}'"
        else:
            # LIKE with a bound parameter — still parameterized, no string-built SQL.
            cur.execute("DELETE FROM users WHERE pseudonym LIKE %s", (SYNTHETIC_PREFIX + "%",))
            scope = f"all '{SYNTHETIC_PREFIX}*' subjects"
        deleted = cur.rowcount
        conn.commit()
    print(f"[SYNTHETIC] reset {scope}: removed {deleted} subject(s) and their data.")


def main() -> None:
    p = argparse.ArgumentParser(description="Synthetic telemetry generator (DEMO data, not real).")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="backfill synthetic days via POST /events")
    g.add_argument("--pseudonym", default=DEFAULT_PSEUDONYM,
                   help=f"must start with '{SYNTHETIC_PREFIX}' (default {DEFAULT_PSEUDONYM})")
    g.add_argument("--days", type=int, default=14, help="how many days to backfill (default 14)")

    r = sub.add_parser("reset", help="delete synthetic subjects (parameterized SQL)")
    r.add_argument("--pseudonym", default=None,
                   help="one subject; omit to delete ALL synthetic-* subjects")

    args = p.parse_args()
    if args.cmd == "generate":
        generate(args.pseudonym, args.days)
    elif args.cmd == "reset":
        reset(args.pseudonym)


if __name__ == "__main__":
    main()
