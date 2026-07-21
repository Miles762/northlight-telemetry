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
(input monitors ignore the OS event payload and call count-only methods). There
is no content column in the database. As defense-in-depth the API also rejects
content two ways: unexpected fields are refused outright, and the one free-text
field, `app_name`, is allowlisted to the *shape* of a real app display name
(name charset, at most a few words, no URL/domain, `app_focus` events only) so
URLs, paths, and prose sentences are rejected. (The server can't tell a one-word
app name from a one-word secret by inspection — the guarantee that only app
identities arrive comes from the agent, which sends only `localizedName`.)

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

**[`NOTES.md`](./NOTES.md) has the full setup and is the source of truth** for
running this — it's the required deliverable. The short version: bring up three
shared services in order — **database → backend → dashboard** — then feed the
dashboard one of two ways.

- **Real data (primary demo, source of truth):** run the Swift agent, click
  **Start collection (consent)**, use your computer for a few minutes. The
  dashboard connects on its own and auto-refreshes, so your usage appears without
  any manual step. Your own usage, captured on your machine.
- **Synthetic data (optional):** run the labeled generator to backfill extra days
  so trend/baseline charts have history. Every synthetic subject's pseudonym
  starts with `synthetic-` (visible on the dashboard) and it POSTs through the same
  `POST /events` endpoint — never passed off as real.

See **[`NOTES.md § Setup`](./NOTES.md#setup--run-the-pieces-in-order)** for exact
commands (both paths) and **[`§ Real vs synthetic data`](./NOTES.md#real-vs-synthetic-data)**.

---

## Design at a glance

- **Real captured telemetry is the source of truth.** Synthetic only backfills
  trend/baseline history and is clearly labeled (`synthetic-` pseudonym prefix).
- **Privacy-first.** The database keys on a pseudonym — a SHA-256 hash of a random
  on-device install id. No name, email, or device identifier is ever stored; the raw
  id never leaves the machine.
- **Raw vs aggregate.** Raw events are append-only (for recompute/debug) with short
  retention; the dashboard reads day-level aggregates for summary/trends.
- **Transparent scores.** Focus/engagement are traceable v1 heuristics computed in
  `backend/app/aggregate.py` — the weights, worked example, and confidence gating
  are documented in **[`NOTES.md § How the scores are computed`](./NOTES.md#how-the-scores-are-computed)**.

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
