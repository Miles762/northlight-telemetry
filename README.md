# NorthLight — Desktop Telemetry & Clinician Dashboard

A thin, working, end-to-end slice that captures **how** a computer is used —
counts, durations, app names, and coarse power/network/display state — and turns
it into per-day behavioral signals a clinician could review between visits. It
**never captures what is typed, read, or clicked**.

> **These metrics represent behavioral signals and should not be interpreted as
> diagnoses.**

```
Desktop Agent (Swift)  →  FastAPI ingestion  →  PostgreSQL  →  React dashboard
   observe & count         validate & aggregate    raw + aggregate    read-only charts
```

The design principle throughout: **capture activity *level*, never activity
*content*.** The agent records *that* 47 keystrokes happened in a minute — never
*which* keys. Content exclusion is enforced in code at the point of capture
(input monitors ignore the OS event payload and call count-only methods), and
there is no content column anywhere in the database.

---

## What's here

| Path | What it is |
|---|---|
| `agent/` | Swift menu-bar telemetry agent (macOS). The only component that touches the OS. |
| `backend/` | FastAPI ingestion + aggregation. Exactly two endpoints; real SQL migrations. |
| `dashboard/` | React + TypeScript + Vite + Tailwind + Recharts clinician view (read-only). |
| `backend/synthetic.py` | Clearly-labeled synthetic data generator (backfills demo days). |
| `agent/Tests/NorthLightAgentCoreChecks` | Lightweight SwiftPM check for count-only input state. |
| **[`NOTES.md`](./NOTES.md)** | **Setup, architecture, DB design, score formulas, scope cuts.** Start here to run it. |
| **[`PRIVACY.md`](./PRIVACY.md)** | HIPAA / de-identification reasoning (first-person engineering rationale). |

---

## Quick start

Full instructions — including the macOS agent — are in **[`NOTES.md`](./NOTES.md)**.
The short version (no `.env` needed; every component defaults to localhost).
Optional overrides are listed in [`.env.example`](./.env.example).

First bring up the three shared services and leave them running:

```bash
# 1. Database + migrations
docker run -d --name nl_pg -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=northlight postgres:16
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/northlight"
for f in backend/migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done

# 2. Backend  → http://127.0.0.1:8000
cd backend && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --port 8000

# 3. Dashboard  → http://localhost:5173  (open this in a browser)
cd dashboard && npm install && npm run dev
```

With those up, get data onto the dashboard one of two ways. **Refresh the browser
tab to see new data** — it does not auto-update.

### Path A — Real capture (the source of truth, primary demo)

Build the agent, wrap it in an `.app` bundle, and launch it:

```bash
cd agent && swift build -c release && ./Scripts/make-app-bundle.sh && open ./NorthLightAgent.app
```

Then in the agent window: click **Start collection (consent)** — *collection is OFF
until you do this* — grant macOS **Input Monitoring** when prompted, use your
computer normally for a few minutes, and refresh the dashboard. New activity lands
~60 s later (the agent sends in one-minute buckets). This is the real path: the
data is your own usage, captured on your machine.

### Path B — Synthetic backfill (optional, for multi-day trends)

A half-day of real capture won't fill the trend/baseline charts, so a **clearly
labeled** generator backfills extra days:

```bash
cd backend && ./.venv/bin/python synthetic.py generate --days 16
```

It is never passed off as real: every synthetic subject's pseudonym starts with
**`synthetic-`** (visible on the dashboard's subject label), it POSTs through the
same `POST /events` endpoint with full validation (no privileged insert path), and
it emits only counts/durations/app-names — no content. Reset with
`./.venv/bin/python synthetic.py reset`.

---

## Design at a glance

- **Real captured telemetry is the source of truth.** The synthetic generator only
  backfills extra days for trend/baseline demos and is clearly labeled (every
  synthetic subject's pseudonym starts with `synthetic-`, visible on the dashboard).
- **Privacy-first.** The database keys on a pseudonym — a SHA-256 hash of a random
  on-device install id. No name, email, or device identifier is ever stored; the raw
  id never leaves the machine.
- **Raw vs aggregate.** Raw events are append-only (for recompute/debug) with short
  retention; the dashboard uses day-level aggregates for summary/trends and
  latest-day content-free raw rows for app usage/timeline markers.
- **Transparent scores.** Focus = 40% active / 30% sustained app use / 20% low
  switching / 10% consistency; computed in `backend/app/aggregate.py` and
  explained in [`NOTES.md`](./NOTES.md).

## Checks

```bash
cd agent && swift run NorthLightAgentCoreChecks
cd backend && ./.venv/bin/python -m unittest discover -s tests
cd dashboard && npm run build && npm run lint
cd dashboard && npm run a11y
cd dashboard && npm run test:a11y
```

## Stack

Swift/SwiftUI · FastAPI (Python) · PostgreSQL (real migrations) · React + TypeScript
+ Vite + Tailwind + Recharts.
