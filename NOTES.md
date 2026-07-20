# NOTES.md — NorthLight Desktop Telemetry & Clinician Dashboard

A thin, working, end-to-end slice: **Swift menu-bar agent → FastAPI ingestion →
PostgreSQL → React dashboard.** It captures *how* a computer is used (counts,
durations, app names) — **never what is typed, read, or clicked** — and turns it
into per-day behavioral signals a clinician could review between visits.

> **Real captured telemetry from the agent on my own machine is the source of
> truth and the main demo path.** A synthetic generator only *backfills extra
> days* so the trend/baseline charts have history to show; it is clearly labeled
> and never presented as real (see [§ Real vs synthetic data](#real-vs-synthetic-data)).

> **These metrics represent behavioral signals and should not be interpreted as
> diagnoses.** Privacy reasoning lives in [`PRIVACY.md`](./PRIVACY.md).

---

## Repository layout

```
Parva/
├── backend/                 FastAPI ingestion + aggregation + dashboard API
│   ├── app/                 db.py · models.py · aggregate.py · main.py
│   ├── migrations/          real CREATE TABLE / migration SQL (not ORM models)
│   ├── synthetic.py         labeled synthetic data generator (generate / reset)
│   └── requirements.txt     pinned backend deps
├── agent/                   Swift menu-bar telemetry agent (macOS)
│   ├── Sources/NorthLightAgent/  Pseudonym · Telemetry · Batcher · main
│   └── Scripts/make-app-bundle.sh
├── dashboard/               React + TS + Vite + Tailwind + Recharts
│   └── src/                 api.ts · App.tsx · index.css
├── NOTES.md   ← you are here
└── PRIVACY.md               Part 3 in full (HIPAA / de-identification reasoning)
```

---

## Prerequisites

- **PostgreSQL 13+** (I used 16). Either a local install or Docker.
- **Python 3.11+** for the backend and generator.
- **Node 18+** for the dashboard.
- **macOS 13+ with Swift 6 / Command Line Tools** for the agent. (No full Xcode
  needed — see [agent notes](#4-desktop-agent-macos).)

Nothing needs a `.env`. Every component reads its config from an environment
variable **with a localhost default**, so the whole thing runs zero-config:

| Component | Env var | Default |
|---|---|---|
| Backend | `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/northlight` |
| Dashboard | `VITE_API_URL` | `http://127.0.0.1:8000` |
| Agent / generator | `NORTHLIGHT_BACKEND_URL` / `BACKEND_URL` | `http://127.0.0.1:8000` |

---

## Setup — run all four pieces

### 1. Database + migrations

```bash
# Option A — Docker (self-contained):
docker run -d --name nl_pg -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=northlight postgres:16

# Option B — local Postgres:
createdb northlight

# Apply the migrations in order (works for either option):
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/northlight"
for f in backend/migrations/*.sql; do
  psql "$DATABASE_URL" -f "$f"
done
```

### 2. Backend (FastAPI)

```bash
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/northlight"
./.venv/bin/uvicorn app.main:app --port 8000
# → http://127.0.0.1:8000/docs  (POST /events, GET /dashboard)
```

### 3. Dashboard (React)

```bash
cd dashboard
npm install
npm run dev
# → http://localhost:5173
```

If there is no data yet the dashboard says so. Get data by running the agent
(below) or the synthetic generator (further below), then refresh.

### 4. Desktop agent (macOS)

The machine used to build this had Swift 6 Command Line Tools but **not full
Xcode**, so the agent builds with SwiftPM and a script wraps the binary into a
proper `.app` bundle (macOS grants Input Monitoring to a bundled app with a
stable id + usage strings, which a bare terminal binary doesn't reliably get):

```bash
cd agent
swift build -c release
./Scripts/make-app-bundle.sh
open ./NorthLightAgent.app        # a menu-bar item appears (◎ NL)
```

Then, in the menu-bar item:
1. Read **"Collected: counts, durations, app names — never content"** (the
   plain-language privacy statement).
2. Click **Start collection (consent)** — *collection is OFF until you do this.*
3. On first run macOS will ask for **Input Monitoring** permission (needed for
   keyboard/mouse *counts* only). Grant it in System Settings → Privacy &
   Security → Input Monitoring. Session and app-focus signals work without it.

The agent buckets activity every 60 s and POSTs to the backend. Use the
computer normally for a few minutes, then open the dashboard.

### 5. Synthetic data (optional, for multi-day trends)

See [Real vs synthetic data](#real-vs-synthetic-data) below.

---

## Architecture — four components, one responsibility each

```
Desktop Agent (Swift)        observe local activity → privacy-safe counts/durations → batch → POST
      │  batched JSON over HTTP (localhost; TLS in production)
      ▼
Backend (FastAPI)            validate & persist batches; recompute the day's aggregates on write;
      │  parameterized SQL   serve derived metrics. Exactly two endpoints.
      ▼
PostgreSQL                   raw telemetry_events + derived sessions/daily_metrics; source of truth;
      │  GET /dashboard      where retention is enforced.
      ▼
React Dashboard              read-only clinician view; turns aggregates into charts + baseline,
                             with persistent "signal, not diagnosis" framing.
```

- **Agent** is the *only* component that touches the OS, and the *only* place the
  content-exclusion boundary is enforced (input monitors increment a counter and
  discard the event in the same closure — visible in `Telemetry.swift`).
- **Backend** holds no logic beyond ingestion + aggregation retrieval. Endpoints
  are exactly `POST /events` and `GET /dashboard`.
- **PostgreSQL** separates raw (correctness/recompute) from aggregates
  (speed/lower exposure).
- **Dashboard** reads almost exclusively from the day-level aggregates.

---

## Database design

Real migrations (`backend/migrations/*.sql`), not ORM models.

### Raw vs aggregated

| | Table(s) | Purpose | Trade-off |
|---|---|---|---|
| **Raw** | `telemetry_events` | append-only per-bucket observations | recompute metrics after formula changes, debug the pipeline; **higher volume, higher privacy exposure** |
| **Derived** | `sessions` | active spans bounded by idle/lock/sleep | feed the "sustained session" score component + timeline |
| **Aggregate** | `daily_metrics` | one row per user per day | **fast dashboard reads, lower exposure** (a day summary reveals far less than the event stream) |

The core data-modeling decision: **keep raw for correctness/recompute, serve
aggregates for speed/privacy.** The dashboard reads aggregates almost exclusively.

There is **no content column anywhere** in the schema — not for keystrokes, text,
URLs, or screen contents. The only text columns are `app_name` and an opt-in,
default-NULL `window_title`. Content cannot be persisted because there is nowhere
to put it.

### Indexes and the queries they serve

| Index | Query pattern |
|---|---|
| `telemetry_events (user_id, ts)` | dominant scan: one user's events in a time range, to build a day's aggregates |
| `telemetry_events (user_id, event_type, ts)` | per-signal metrics (sum keyboard counts, count app switches) — filtered range scan, already user-scoped |
| `sessions (user_id, start_time)` | sessions per user in start order (timeline + daily rollup) |
| `daily_metrics` UNIQUE `(user_id, date)` | dashboard retrieval key **and** idempotent-upsert conflict target (one row per user-day) |

I chose the composite `(user_id, event_type, ts)` over a bare `(event_type)`
index because **every** query is already scoped to a single user, so a lone
`event_type` index would rarely be selective. I did **not** add a
separate index on `daily_metrics (user_id, date)` — the `UNIQUE` constraint
already creates exactly that index; a second one would duplicate it.

### Idempotent ingestion

`daily_metrics` upserts on `(user_id, date)`, so re-aggregating a day overwrites
rather than duplicates. To also make **raw insertion** idempotent — so a retried
POST doesn't double-count — the agent assigns each batch a UUID `batch_id` and
reuses it on retry; the backend records ingested `batch_id`s (`ingest_batches`,
migration `0003`) and skips a batch it has already seen.

> **Note on the extra table:** the core schema is the four tables above (users,
> telemetry_events, sessions, daily_metrics). I added one small ledger table,
> `ingest_batches`, purely to make raw ingestion idempotent under retries. It
> records only an opaque batch id, a user, a count, and a time — no telemetry, no
> content — and exists solely so a resent batch is recognized and skipped rather
> than re-inserted. I kept it separate rather than fold the flag into an existing
> table so the dedup concern stays isolated and easy to reason about.

### Retention (`0002_retention.sql`)

Retention length tracks sensitivity **inversely**:

- **Raw events:** 30–90 days (MVP horizon pinned at 90). Highest exposure,
  shortest life. Long enough to establish a baseline and recompute after a
  formula change; short enough to bound standing privacy risk.
- **Aggregates + sessions:** longer (1–2 years). They carry the trend value with
  far lower re-identification risk.

Encoded as an executable function `enforce_raw_retention(retain_days)` that
deletes only raw events past the horizon and returns the count. **Automated
scheduling is [FUTURE]** and intentionally not built — the policy lives as
reviewable, hand-runnable code (`SELECT enforce_raw_retention(90);`), nothing
calls it automatically.

---

## How the scores are computed

Both scores are **transparent v1 heuristics** on a 0–100 scale, computed in
`backend/app/aggregate.py` from the raw signal so a clinician (or reviewer) can
trace every number. The reference constants below are the v1 anchors defined at
the top of that file; calibration against real clinician-labeled outcomes is
[FUTURE].

**Component sub-scores (each normalized to 0–1):**

| Sub-score | How | Anchor (v1) |
|---|---|---|
| Active time | active minutes ÷ a "full" active day | 6 h = 1.0 |
| Sustained app use | mean `app_focus` duration | 5 min = 1.0 |
| Low switching | 1 − (switches per active hour ÷ ceiling) | 30 switches/hr → 0 |
| Consistency | distinct hours-of-day with any activity | 8 hours = 1.0 |

> **`app_switch` vs `app_focus` — a distinction that matters.** The agent emits two
> separate signals: `app_focus` events carry per-app *duration* (and the open app's
> running span is re-emitted every bucket so usage totals stay accurate), while a
> dedicated `app_switch` event carries the count of *real* foreground-app changes.
> `app_switch_count` is summed from `app_switch` events — **not** inferred from the
> number of `app_focus` rows, which would count buckets-of-focus as switches and
> badly inflate the fragmentation signal for a user who stays in one app. (An earlier
> version made exactly that mistake; it's fixed, and the two-signal split is why.)

**Focus score** — a fixed weighting of the four sub-scores:

```
Focus = 100 × (0.40·active + 0.30·sustained + 0.20·low_switch + 0.10·consistency)
```

**Engagement score** — "showed up, stayed, and did so consistently." Its three
components (active time, sustained sessions, consistent activity) don't have a
prescribed weighting the way Focus does, so I used the simplest defensible split
and documented it here and in code:

```
Engagement = 100 × (0.50·active + 0.30·session_duration + 0.20·consistency)
```

*(`session_duration` reuses the sustained-span sub-score as the proxy for
"sustained sessions rather than fleeting ones.")*

**Baseline / anomaly:** defined relative to the person's *own*
trailing mean, never a population norm. The dashboard compares the latest day's
active minutes to the mean of prior days; a deviation beyond ±40% is surfaced as
**"worth a look"** — a nudge to check in, explicitly *not* an abnormality.

> **Worked example (verified against the running code):** a day with 180 active
> min, mean focus span 800 s, 3 app switches, activity across 3 hours →
> Focus **73.08**, Engagement **62.5**. The math is in `aggregate.py` and matches
> the API output exactly.

---

## Real vs synthetic data

**Real captured telemetry is the source of truth and the primary demo path.**
The synthetic generator exists only because trend/baseline charts need several
days of history that a half-day exercise doesn't produce.

- **Which is which on the dashboard:** every synthetic subject's pseudonym starts
  with **`synthetic-`** (e.g. `synthetic-demo-001`). That prefix is visible in the
  database *and* on the dashboard's subject label, so synthetic days are never
  confusable with real capture. Real agent subjects are a hashed install id with
  no such prefix.
- **Same pipeline:** the generator POSTs through the real `POST /events` endpoint
  with full validation — no privileged insert path. Generating data also
  exercises the real ingestion + aggregation.
- **Privacy-safe:** it emits only the same count/duration/app-name shapes the
  agent does. No content.

```bash
cd backend
export BACKEND_URL="http://127.0.0.1:8000"
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/northlight"

# generate 14 synthetic days into synthetic-demo-001:
./.venv/bin/python synthetic.py generate --days 14

# reset: delete ALL synthetic-* subjects (real data is never touched):
./.venv/bin/python synthetic.py reset

# reset just one subject:
./.venv/bin/python synthetic.py reset --pseudonym synthetic-demo-001
```

`generate` refuses any pseudonym not starting with `synthetic-`. `reset` deletes
via parameterized SQL against the DB directly (there is deliberately **no delete
endpoint** — the backend stays at exactly two endpoints); `ON DELETE CASCADE`
clears the subject's events/sessions/metrics/batches.

**Screenshots in this submission** that show multiple days of trends use
synthetic backfill (clearly labeled `synthetic-…` in the subject line); the
single-day/live capture path is the real agent.

---

## Scope cuts (deliberately not built, and why)

Deliberately unbuilt — auth, SSO, multi-tenancy, RBAC, cloud deploy, audit
logging, ML scoring, EHR/FHIR integration, mobile, warehouse pipeline. Each is
deferred because it adds operational surface without changing what a reviewer
learns about the design reasoning in a half-day slice.

Slice-level decisions I made where the brief left it open, each noted so it's
defensible rather than accidental:

- **On-write aggregation** (not a scheduled rollup) — simplest to run/demo; the
  dashboard is always current.
- **UTC day bucketing** — a real deployment buckets by the patient's local
  timezone; UTC is fine for the single-machine slice. Noted in `aggregate.py`.
- **`event_type` is free `TEXT` with no DB `CHECK`** — the API validates it
  strictly (`models.py`), keeping the migration flexible; the guarantee lives in
  app code.
- **One DB connection per request** (no pool) — more than enough for one
  low-volume machine; a pool is a [FUTURE] optimization.
- **Battery / network / display signals** — [FUTURE]; they don't change the core
  metrics.
- **Window titles** — captured **never** by default (opt-in, sensitive); see
  `PRIVACY.md`.
- **`ingest_batches` table** — one small ledger table added purely for retry
  idempotency (explained above).
```

Verification I ran while building each piece (migrations apply on PG16; agent
wire format POSTs 200 and produces correct scores; dashboard renders in light +
dark against live data; synthetic generate/reset scope correctly) is described
inline in the relevant sections above.
