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
│   ├── Sources/NorthLightAgentCore/ count-only input abstraction
│   ├── Tests/NorthLightAgentCoreChecks/ lightweight SwiftPM check
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
  needed — see [agent notes](#3a-real-data--desktop-agent-macos).)

Nothing needs a `.env`. Every component reads its config straight from an
environment variable **with a localhost default** (`os.environ.get(...)`), so the
whole thing runs zero-config — you never create or load a `.env` file to test it.
The steps below just `export` the couple of vars they need inline.
[`.env.example`](./.env.example) is a **reference card** listing all four config
knobs and their defaults in one place; read it only if you want to change a port
or host. It is not loaded by anything at runtime.

| Component | Env var | Default |
|---|---|---|
| Backend | `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/northlight` |
| Dashboard | `VITE_API_URL` | `http://127.0.0.1:8000` |
| Agent / generator | `NORTHLIGHT_BACKEND_URL` / `BACKEND_URL` | `http://127.0.0.1:8000` |

---

## Setup — run the pieces in order

### 1. Database + migrations

**Option A — Docker (recommended; fully self-contained).** Needs nothing
pre-installed but Docker — it pulls Postgres and pipes the migrations *into* the
container's built-in `psql`, so it works even with no Postgres client on your
machine. Use this unless you already run Postgres natively:

```bash
docker run -d --name nl_pg -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=northlight postgres:16
sleep 3   # let Postgres finish starting

# apply migrations in order, through the container (no host psql required):
for f in backend/migrations/*.sql; do
  docker exec -i nl_pg psql -U postgres -d northlight -v ON_ERROR_STOP=1 < "$f"
done
```

**Option B — local Postgres (fallback; only if you *already* run Postgres and
have the `psql` client).** This is not a from-scratch installer — it assumes a
running Postgres and an existing `psql`. If you don't have those, use Option A
instead of installing Postgres by hand:

```bash
createdb northlight
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/northlight"
for f in backend/migrations/*.sql; do
  psql "$DATABASE_URL" -f "$f"
done
```

Either way you end up with five tables: `users`, `telemetry_events`, `sessions`,
`daily_metrics`, `ingest_batches`.

### 2. Backend (FastAPI)

```bash
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/northlight"
./.venv/bin/uvicorn app.main:app --port 8000
# → http://127.0.0.1:8000/docs  (POST /events, GET /dashboard)
```

### 3. Get data — choose ONE path

Steps 1–2 are the same for everyone. Now put data behind the dashboard by running
**either** the real agent (**3a**) **or** the synthetic generator (**3b**). Then
open the dashboard **last** (step 4).

**Order matters:** start the dashboard *after* the backend is up and data exists.
Opening it before the backend finishes starting is the one thing that produces the
transient `404` in the troubleshooting note below — avoid it simply by opening the
dashboard last, for both the real and synthetic paths.

#### 3a. Real data — desktop agent (macOS)

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

The agent installs OS observers only after Start, buckets activity every 60 s,
and POSTs to the backend. Pause flushes the current consented partial bucket,
then removes the observers and clears in-memory counters. Use the computer
normally for a few minutes, then open the dashboard (step 4).

#### 3b. Synthetic data — generator (optional, for multi-day trends)

Instead of the agent, backfill several days of **clearly labeled** history so the
trend/baseline charts have something to show:

```bash
cd backend
export BACKEND_URL="http://127.0.0.1:8000"
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/northlight"

# backfill 14 synthetic days into subject 'synthetic-demo-001':
./.venv/bin/python synthetic.py generate --days 14

# remove all synthetic subjects when done (real data is never touched):
./.venv/bin/python synthetic.py reset
```

The subject label on the dashboard starts with **`synthetic-`**, so synthetic days
are never confusable with real capture. Why this exists, the safety guarantees, and
per-subject reset are in [Real vs synthetic data](#real-vs-synthetic-data) below.

### 4. Dashboard (React)

Opening the dashboard last — after the backend (step 2) is up and data exists
(step 3) — means it shows your data immediately. But it no longer *has* to be
last: it connects on its own and auto-refreshes, so if you open it early it just
waits and fills in by itself once the backend is reachable (see the note below).

```bash
cd dashboard
npm install
npm run dev
# → http://localhost:5173
```

The dashboard **connects on its own** and then **auto-refreshes every 60 s**, so
once it's open new activity (the agent sends in 60 s buckets) appears without you
touching anything.

**Order doesn't have to be perfect.** You can open the dashboard before the
backend is up. Until the backend answers it shows a calm *"Connecting to the
telemetry service…"* — no error, no button, no HTTP status — and it **polls in the
background and loads itself the instant the backend is reachable** (typically
within a second of the backend coming up). There is nothing to click. If it stays
on that message longer than ~15 s it adds a hint to check that the backend is
running (`uvicorn app.main:app --port 8000`), but it keeps polling and still
recovers on its own the moment the backend appears — no refresh needed.

To sanity-check the backend directly at any time:
`curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/dashboard` should
print `200`.

### Stopping / clean slate

Two pieces outlive the terminal you started them in, so closing terminals alone
does **not** stop everything: the **Postgres container** (a Docker daemon
process) and the **menu-bar agent** (a GUI app). Tear everything down — remove the
database, stop the agent, backend, and dashboard — with one copyable line:

```bash
docker rm -f nl_pg 2>/dev/null; pkill -f NorthLightAgent; pkill -f "uvicorn app.main"; pkill -f vite; echo "✅ clean slate"
```

(`pkill` prints a non-zero/✗ for any piece that wasn't running — that's just
"nothing to kill," not an error.)

To wipe data **without** removing the database (keep the container and schema,
skip re-running migrations), reset just the rows instead:

```bash
# synthetic subjects only (real data untouched):
cd backend && ./.venv/bin/python synthetic.py reset
```

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
  content-exclusion boundary is enforced (input monitors ignore the event payload
  and call count-only methods — visible in `Telemetry.swift`).
- **Backend** holds no logic beyond ingestion + aggregation retrieval. Endpoints
  are exactly `POST /events` and `GET /dashboard`.
- **PostgreSQL** separates raw (correctness/recompute), derived sessions
  (active-span reconstruction), and aggregates (speed/lower exposure).
- **Dashboard** reads day-level aggregates for summary/trends and reads the
  latest day's content-free raw events only for app usage and the timeline.

---

## Database design

Real migrations (`backend/migrations/*.sql`), not ORM models.

### Raw vs aggregated

| | Table(s) | Purpose | Trade-off |
|---|---|---|---|
| **Raw** | `telemetry_events` | append-only per-bucket observations | recompute metrics after formula changes, debug the pipeline; **higher volume, higher privacy exposure** |
| **Derived** | `sessions` | merged active spans derived from raw `active` events | easier timeline/session reasoning; rebuildable from raw data |
| **Aggregate** | `daily_metrics` | one row per user per day | **fast dashboard reads, lower exposure** (a day summary reveals far less than the event stream) |

The core data-modeling decision: **keep raw for correctness/recompute, serve
aggregates for speed/privacy.** The dashboard uses aggregates for the headline
view; latest-day app usage and timeline are derived from raw events because they
are inherently intraday views.

There is **no content column anywhere** in the schema — not for keystrokes, text,
URLs, window titles, or screen contents. The only telemetry text column is
`app_name`. Content exclusion is enforced primarily **at capture** (the agent
sends only `NSRunningApplication.localizedName`); the API adds defense-in-depth:
content named as content is rejected by the field allowlist (`extra="forbid"`),
and `app_name` is allowlisted to the *shape* of a real app display name — name
charset only, at most a few words, no URL/domain, `app_focus` events only — so
URLs, paths, and prose sentences are rejected. Honest limit: the server can't
distinguish a one-word app name from a one-word secret by inspection, so this
layer rejects content-*shaped* input, not every string; the guarantee that only
app identities arrive is the agent, not the validator. (See
`backend/app/models.py` and its contract tests.)

### Indexes and the queries they serve

| Index | Query pattern |
|---|---|
| `telemetry_events (user_id, ts)` | dominant scan: one user's events in a time range, to build a day's aggregates |
| `telemetry_events (user_id, event_type, ts)` | per-signal metrics (sum keyboard counts, count app switches) — filtered range scan, already user-scoped |
| `sessions (user_id, start_time)` | sessions per user in start order for timeline/session review |
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

The API also caps each ingest request at **500 events**. That keeps one POST from
turning into an unbounded `executemany()` transaction. The agent mirrors that
contract by flushing at most 500 events per request, retrying the same chunk with
the same `batch_id` on failure, and bounding its local unsent buffer at 5,000
events. If the backend stays unavailable past that local cap, the agent drops the
oldest unsent events instead of growing memory without limit.

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

In plain language: **Focus** answers *"how sustained and un-fragmented was the
activity?"* (rewards being active, staying in one app rather than app-hopping, and
spreading activity through the day); **Engagement** answers *"did the person show
up, stay, and do so consistently?"* (rewards presence and sustained use over
fleeting bursts).

> **Expected: a short capture yields very low scores — this is correct, not a bug.**
> Active time is normalized against a *6-hour* day (see anchors below), so a
> one- or two-minute test capture produces single-digit Focus/Engagement (e.g.
> `3.4` / `4.6`) — the score is faithfully reporting "almost no activity was
> observed," not malfunctioning. A full day of real use, or synthetic backfill,
> lands scores in realistic ranges (a 180-active-minute day scores Focus ≈ 73).
> Likewise **"confidence" is not shown on a single day**: it is a data-sufficiency
> label on the *baseline* card (§ below), and with fewer than two days the card
> reads "needs at least two collected days" by design.

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
components (active time, sustained app spans, consistent activity) don't have a
prescribed weighting the way Focus does, so I used the simplest defensible split
and documented it here and in code:

```
Engagement = 100 × (0.50·active + 0.30·session_duration + 0.20·consistency)
```

*(`session_duration` reuses the sustained app-span sub-score as the v1 proxy for
"sustained activity rather than fleeting interactions"; `sessions` is populated
for review/timeline use and could become the score input in a later formula.)*

**Baseline / anomaly:** defined relative to the person's *own*
trailing mean, never a population norm. The dashboard compares the latest day's
active minutes to the mean of prior days, but it gates alerts on data
sufficiency:

| Prior days | Confidence | Alert behavior |
|---|---|---|
| 1-2 | insufficient | show context only; no alert |
| 3-6 | low | show context only; no alert |
| 7-13 | moderate | alert only beyond ±50% |
| 14+ | higher | alert beyond ±40% |

The dashboard labels confidence and explains sparse-data cases as “more days
needed” rather than surfacing an alarming flag. When an alert is allowed it is
still phrased as **"worth a look"** — a nudge to check in, explicitly *not* an
abnormality.

> **Worked example (verified against the running code):** a day with 180 active
> min, mean focus span 800 s, 3 app switches, activity across 3 hours →
> Focus **73.08**, Engagement **62.5**. The math is in `aggregate.py` and matches
> the API output exactly.

---

## Real vs synthetic data

**Real captured telemetry is the source of truth and the primary demo path.**
The synthetic generator exists only because trend/baseline charts need several
days of history that a half-day exercise doesn't produce.

`real-dashboard.png` (repo root) is the dashboard rendering **real telemetry
captured from my own machine** — the agent built from source, Input Monitoring
granted, **Start collection (consent)** pressed, then ~55 minutes of normal use.
It shows a hashed subject (`c4ef7d2d…`, no `synthetic-` prefix), real
focus/engagement scores from that session, real foreground app names only
(Safari, Code, Google Chrome) — no window titles, URLs, or content — and the
baseline panel populated from real activity.

> **One honest note on the dates.** This was a single continuous evening session
> (~19:41–20:37 EDT). It appears as two days (`2026-07-21` / `2026-07-22`) because
> aggregation buckets by **UTC** date and the session crossed 00:00 UTC (8pm EDT).
> That is the UTC-bucketing simplification flagged in `backend/app/aggregate.py`
> (`_local_day`): a real deployment would bucket by the patient's local timezone.
> The split is a demonstration of that documented limitation, not two real days.

![Dashboard rendering real captured telemetry from my own machine](real-dashboard.png)

- **Which is which on the dashboard:** every synthetic subject's pseudonym starts
  with **`synthetic-`** (e.g. `synthetic-demo-001`). That prefix is visible in the
  database *and* on the dashboard's subject label, so synthetic days are never
  confusable with real capture. Real agent subjects are a hashed install id with
  no such prefix.
- **Same pipeline:** the generator POSTs through the real `POST /events` endpoint
  with full validation — no privileged insert path. Generating data also
  exercises the real ingestion + aggregation.
- **Privacy-safe:** it emits only the same count/duration/app-name/system-state
  shapes the agent does. No content.

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
- **Window titles** — captured **never** and rejected by the backend contract; see
  `PRIVACY.md`.
- **`ingest_batches` table** — one small ledger table added purely for retry
  idempotency (explained above).

## Accessibility

A clinician dashboard for a brain-health product will be read by clinicians and
patients with visual, cognitive, attention, or motor differences, so
accessibility is treated as a design requirement, not a polish pass. What the
dashboard does today, and how it's checked:

- **Color contrast (the primary low-vision concern) meets WCAG 2.1 AA.** Body
  text is near-black on off-white in light mode (`#0b0b0b` on `#f9f9f7`) and
  near-white on near-black in dark mode — both well above the 4.5:1 AA floor. The
  palette re-resolves on OS light/dark change, so either theme stays compliant.
- **Information is never conveyed by color alone.** Every chart carries a direct
  text label (e.g. `Active 31%`, legend dots paired with text, tooltips), so
  low-vision and color-blind users don't have to distinguish hues to read a value.
- **Semantic structure for magnifiers and screen readers.** Real headings, a
  `role="note"` on the persistent "signal, not diagnosis" disclaimer, and labeled
  controls — no icon-only unlabeled buttons, no placeholder-as-label inputs.
- **Two automated gates, both run in the checks below:**
  - `npm run a11y` — fast static smoke check (labels present, roles set, no
    icon-only unlabeled buttons).
  - `npm run test:a11y` — builds the app, renders it in Chromium via Playwright,
    and runs **axe-core with the `wcag2a` + `wcag2aa` rule sets**, failing on any
    serious/critical violation (color-contrast, name/role/value, ARIA, etc.).
    Currently **passing with zero serious/critical violations**.

**Honest limit (so this isn't oversold):** automated axe testing catches roughly
a third to a half of WCAG issues. It does **not** verify real screen-reader
narration flow, keyboard-only navigation, or 200% zoom reflow. The next
accessibility step I'd take is a manual screen-reader + keyboard-only pass; I
scoped that as [FUTURE] for a half-day slice and note it here rather than imply
full coverage.

---

## Verification

```bash
cd agent && swift build -c release
cd agent && swift run NorthLightAgentCoreChecks
cd backend && ./.venv/bin/python -m unittest discover -s tests
cd dashboard && npm run build
cd dashboard && npm run lint
cd dashboard && npm run a11y        # static a11y smoke check
cd dashboard && npm run test:a11y   # axe-core (wcag2a+2aa) on the rendered app
```

Beyond the checks above, I verified migrations against Postgres 16 and posted
synthetic data through `POST /events`; `/dashboard` returned populated daily
metrics, app usage, timeline markers, and baseline output, while the database
populated derived `sessions` rows from the raw active events.
