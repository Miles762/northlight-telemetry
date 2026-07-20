# Coding interview: desktop telemetry + clinician dashboard

## Scenario

NorthLight is a fictional digital-health company that runs remote-monitoring programs for clinics. Part of its
product is a small desktop companion that runs on a patient's computer,
observes how they use it, and turns that into signal a clinician can use to
understand engagement and functioning between visits. You're building a
first version of that pipeline, end to end, on your own machine, using your
own real usage as the data.

Everything you show us
should come from your own software suite running on your own computer. We will judge
this by running/reading what you submit and by your `NOTES.md` — there is no
automated grading against fixtures.

**Suggested time:** this is a bigger exercise than a typical take-home
because it spans three concerns (capture agent, storage, dashboard). Budget
roughly half a day. If you have to cut scope, say what and why in
`NOTES.md` — we'd rather see a smaller, well-reasoned slice than a rushed
attempt at all of it.

## Part 1 — Desktop telemetry agent

Build a small local agent in swift(menu-bar app, background daemon, whatever fits
your platform and language of choice) that runs on your own machine, with
your own knowledge and consent, and records activity telemetry while you
use your computer normally during the exercise. 

Capture as much *activity* signal as you reasonably can — this should read
as "every piece of telemetry you can get from a laptop," not a token
example. At minimum:

- Session boundaries: when the machine is active vs. idle/locked/asleep.
- Keyboard and mouse **activity** — counts/frequency of input events per
  time bucket (e.g. keystrokes per minute, clicks per minute, scroll
  events).
- Foreground application changes — which app has focus and for how long,
  and how often focus switches (a proxy for attention fragmentation).
- Window title of the foreground app, if your platform exposes it.
- System-level signals: screen lock/unlock, sleep/wake, display
  connect/disconnect, battery/power state, network connectivity changes.

**One deliberate, non-negotiable scope boundary: do not log the actual
content of what's typed, viewed, or clicked.** Capture *that* 47 keystrokes
happened in a minute, not *which* keys or characters. Capture *that* the
foreground app changed to a browser, not the URL or page contents. Add in your notes why you think this is necessary to capture the actual keystroke data and instead just the telemetry data. 

## Part 2 — Storage

Persist everything the agent captures in a real SQL database (Postgres
preferred; note in `NOTES.md` if you substituted something else to keep the
exercise self-contained, and why).

Along with your schema/migration files, write up notes covering:

- How you modeled raw events vs. any derived/aggregated tables, and why.
- Indexing choices and what query pattern they support.
- A retention policy: how long would raw activity data live in a real
  deployment of this, and what would you do differently for aggregated
  vs. raw data.

We want to see actual `CREATE TABLE`/migration files, not just ORM models.

## Part 3 — HIPAA and anonymization notes

Write a dedicated document (`PRIVACY.md` or a section in `NOTES.md`) that
treats this as if it were feeding a real HIPAA-covered clinical platform,
even though nothing here touches real patient data. Cover at minimum:

- Which fields you're capturing would be considered identifiable or
  sensitive in a real deployment, and why.
- How you'd de-identify or pseudonymize this data at rest and in transit —
  be concrete (e.g. what gets hashed, what gets dropped, what never leaves
  the device unaggregated).
- Why you scoped out literal keystroke/content logging in Part 1, and what
  you'd say to a clinician or patient who asked what is and isn't recorded.
- A data-minimization argument: for each signal you capture, what's the
  specific clinical/product justification for keeping it.
- Retention and deletion recommendations, and who you imagine should have
  access to raw vs. aggregated data.

This section is not a formality — how carefully you reason about it is a
real part of how we evaluate the exercise.

## Part 4 — Clinician-facing dashboard

Build a dashboard that turns the raw telemetry into metrics a clinician
could plausibly use to understand a patient's day-to-day engagement. Some
directions (pick and justify your own set rather than treating this as a
checklist):

- A derived "focus" or "engagement" score per day, and how you calculated
  it from the raw signal.
- Attention fragmentation — how often focus switches between apps.
- Daily active/idle time and a trend over the days you collected data.
- Anything you'd flag as anomalous relative to the person's own baseline.


## What to submit

- Source for the agent, storage layer (schema/migrations included), and
  dashboard.
- `NOTES.md` — how to run all three pieces, the design notes requested in
  Parts 2 and 4, and anything you cut for time.
- `PRIVACY.md` (or the equivalent section in `NOTES.md`) — Part 3 in full.

We're judging this on the working dashboard, the schema/notes, and your own
write-up — not against a fixed rubric or reference solution.
