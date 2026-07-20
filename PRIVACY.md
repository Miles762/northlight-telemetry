# PRIVACY.md — Privacy & HIPAA reasoning

This is written as **my engineering reasoning** — what I chose and why — for a
system that, in a real deployment, would feed a HIPAA-covered clinical platform.
Nothing here touches real patient data, but I designed it as if it did, because
the interesting part of this exercise is *what is safe to collect*, not the
plumbing. Where I made a trade-off I say so plainly.

The one principle everything below follows: **capture activity *level*, never
activity *content*.** I record *that* 47 keystrokes happened in a minute — never
*which* keys.

---

## 1. What I collect, and what makes each field sensitive

Here is the complete set of things that leave the device, and my honest read of
the risk each carries in a real deployment.

### Application names — *collected, moderately sensitive*
The app in focus is a behavioral signal (what shape the day takes, how fragmented
attention is). But an app name can **imply health, financial, or legal context**
on its own: a specific therapy app, a psychiatric-medication tracker, a
bankruptcy-filing tool, a dating app. Knowing someone spent three hours in a
particular named app can be revealing even with no other data. I keep app names
because the clinical value (see §3) is real, but I treat them as sensitive: they
live in raw events with the shortest retention, and the dashboard only ever shows
*aggregate time-in-app*, never a raw timeline of app switches.

### Window titles — *NOT collected by default; the highest-risk field*
Window titles are where privacy goes to die. "Re: layoffs — confidential.docx",
"HIV test results", a browser tab title that is literally the page's headline —
titles routinely **leak content**, which is exactly the thing I promised never to
capture. So this is the field I'm strictest about. In the schema `window_title`
exists as a nullable, opt-in column, and **the agent never populates it** — it
reads only the app's `localizedName`. The column exists so a future, carefully
gated opt-in path *could* exist, but the default and only data path leaves it
NULL. If I had to cut one thing to reduce risk, it would already be cut.

### Activity timestamps — *collected, sensitive by inference*
Every event has a timestamp. Individually harmless, but a **fine-grained timeline
of when someone is awake, working, idle, or asleep is deeply revealing** — it's a
map of a person's day, and it's re-identifying (your daily rhythm is close to a
fingerprint). This is why raw events have short retention and why broader access
is granted to *day-level* aggregates, which collapse the timeline into a summary.

### Behavioral patterns (in aggregate) — *the subtle one*
Even with no name, no email, and only counts and durations, a **multi-day rhythm
is a fingerprint.** "Active 9–11, idle midday, active again 2–5, high app
switching on Fridays" can distinguish and profile an individual. De-identification
that only strips direct identifiers isn't enough here; the shape of the data is
itself identifying. My mitigation is minimization (I keep as little as the signal
needs) plus retention limits on the most granular layer.

### Input counts (keyboard/mouse) — *collected, low sensitivity by design*
These are just integers per minute. There is no way to reconstruct content from a
count, which is the entire reason I chose the count form (see §2).

---

## 2. Data minimization — per-signal justification

For every signal I ask: *why collect it, what does it buy, and is there a
less-invasive form?* If a less-invasive form gives the same value, I take it.

| Signal | Why collected | Value | Less-invasive alternative? |
|---|---|---|---|
| **Keyboard events** | gauge engagement/activity level | per-minute count fully captures "is the person actively interacting" | **Chose counts over content.** A raw keystroke stream adds *zero* clinical value and is catastrophic risk (it's a keylogger for passwords and private text). Content dropped at the source. |
| **Mouse events** | second input channel for "is the person interacting" | useful when keyboard use is low (reading, browsing) | Counts only — no coordinates, no click targets. Same reasoning as keyboard. |
| **App name + focus duration** | shape of the day; which tasks, how long | coarse activity profile | **App name only** — never window title/URL. The name is the minimum that still carries the signal. |
| **App switch count** | proxy for attention fragmentation | a clinically interesting signal (fragmentation trend) | A count, not a log of *which* apps in *what* order — the count carries the fragmentation signal without the revealing sequence. |
| **Active / idle spans** | the day's rhythm; active vs away | backbone of active/idle time and daily trend | Durations only — derived from a single system idle-time number, not from watching individual events. |
| **Lock / unlock, sleep / wake** | session boundaries | when the person is present vs away/asleep | Transition type + timestamp only. Nothing about *why*. |

Two signals I deliberately **did not** collect at all, though the OS offers them:
battery/network/display state ([FUTURE] — they don't change the core metrics) and
anything about *what* woke the machine or *what* was on the lock screen.

---

## 3. Content exclusion — why I never capture content

I never capture **keystrokes/characters, text content, URLs, or screenshots.**
This isn't a nice-to-have; it's the line the whole design is built around, and
it's enforced *in code at the point of capture*, not by a downstream filter.

- **Keystrokes / characters.** The clinical value is *activity level* — is the
  person engaged, how consistently — which a per-minute count captures fully.
  Capturing *which* keys adds nothing clinical and turns the agent into a
  keylogger recording passwords and private messages. Strictly worse on both
  axes, so it's rejected outright. In `Telemetry.swift` the keyboard monitor's
  handler is literally `{ _ in keyboardCount += 1 }` — the event is ignored by
  name; there is no code path that reads the key.
- **Text content.** Same reasoning; there is no field anywhere in the schema to
  store it.
- **URLs.** A URL is content (and often reveals health/financial/legal context).
  The agent reads the app name, never the browser's URL or page.
- **Screenshots.** Never taken. There is no screen-capture API call anywhere in
  the agent. A screenshot is the maximal content leak — it's simply not a
  capability the system has.

The exclusion is **visible and auditable**: input monitors increment a counter
and discard the event payload in the same closure, and there is no content column
in the database, so content cannot be persisted even by mistake.

### What I'd tell a patient or clinician who asked what's recorded

> **What is collected:** how much you use your computer, when you're active vs.
> away, which applications you switch between, and how often — as counts and
> durations.
>
> **What is NOT collected:** the words you type, the passwords you enter, the
> websites you visit, the contents of your screen, or images of anything you do.
>
> **We measure the rhythm of activity, not its content.**

And I'd add: collection is off until you turn it on, the menu-bar item always
shows whether it's running, and you can pause or quit it at any time.

---

## 4. De-identification — what's hashed, what's dropped, what never leaves the device

Concretely, for this implementation:

- **Pseudonymous IDs — the database keys on a `pseudonym`, never a name or
  email.** There is no `name`, `email`, `phone`, `IP`, or `device_serial` column
  anywhere. By construction the database cannot hold a real identity — there is
  nowhere to put one.
- **Hashing identifiers — what never leaves the device.** On first run the agent
  generates a **random UUID** and stores it in one local file. That raw UUID is
  the "local install id." It is **SHA-256 hashed on the device**, and only the
  hash becomes the `pseudonym` that is sent. The raw UUID never leaves the
  machine. (I hash a value that is *already* random and non-identifying — belt
  and suspenders: the seed ties to an install, not a person, and the hash makes
  it irreversible.) It's stable across runs so the backend can accumulate a
  per-person baseline, and it's not derived from hardware, so it doesn't survive
  a reinstall or link across machines.
- **Removing unnecessary metadata — what's dropped.** The riskiest field, the
  **window title, is dropped at the source** (never captured). App names are kept
  but treated as sensitive. Nothing is collected "just in case."
- **Aggregating before wider access — what stays closest to the device.** Raw
  events (the granular, re-identifying layer) stay in the store with the shortest
  retention and the narrowest access. **Broader/clinician access is to day-level
  aggregates** (`daily_metrics`), which collapse the revealing timeline into a
  summary and carry far lower re-identification risk. The dashboard reads
  aggregates almost exclusively.

**Summary:** *hashed* = the local install id (SHA-256, on-device). *Dropped* =
window titles, and any name/email/device identifier (never collected).
*Never leaves the device unaggregated in a real deployment* = the raw
event-by-event timeline should stay closest to the device; what's shared widely
is the day-level rollup.

---

## 5. Security (transit, at rest, access) — and what's [FUTURE]

**Built / designed into the slice:**
- **In transit.** The agent posts JSON to the backend. Locally that's plain HTTP
  on `127.0.0.1` (nothing leaves the machine). In a real deployment this is
  **agent → backend over TLS**, no exceptions — the payload is health-adjacent.
- **At rest.** Telemetry should sit on a **database with encryption at rest**
  enabled (e.g. Postgres on an encrypted volume / TDE). The slice runs on local
  Postgres; the production requirement is encryption-at-rest for the telemetry
  store.
- **Access control (the design that's already reflected in the data model).**
  **Least privilege, with raw and aggregated access separated by role.** Raw
  `telemetry_events` is the sensitive layer — access limited to engineers/systems
  that need it for recompute/debugging, under short retention. Clinicians get the
  day-level aggregates. This raw-vs-aggregate split is the same one that drives
  the retention policy: the more granular and re-identifiable the data, the
  tighter the access and the shorter the life.

**Named as production requirements, [FUTURE], not built here** (they'd add
operational surface without changing the design reasoning the slice demonstrates):
audit logging of every access to raw data, key management / HSM, SSO, formal
RBAC / row-level security, and Business Associate Agreements with any processor.

---

## 6. Retention & deletion, and who accesses what

Retention length tracks sensitivity **inversely** — the most granular,
re-identifiable data expires first:

| Data | Retention | Who should access it | Why |
|---|---|---|---|
| **Raw `telemetry_events`** | 30–90 days (MVP: 90) | engineers/systems for recompute & debugging; **not** general clinician access | crown jewels of privacy risk (fine timeline); short life bounds standing exposure |
| **Sessions / `daily_metrics`** | 1–2 years | clinicians (the intended read audience) | carry the clinical trend value with much lower re-identification risk |

Enforcement in the slice is an executable, hand-runnable function
(`enforce_raw_retention(90)`) that deletes raw events past the horizon and leaves
aggregates untouched. Automated scheduling is **[FUTURE]** — I kept the policy as
reviewable code rather than prose, but nothing runs it automatically in the slice.

**Deletion:** because everything keys on the pseudonymous `users` row with
`ON DELETE CASCADE`, a subject's entire footprint (events, sessions, metrics,
batch ledger) is removed by deleting that one row — the mechanism a real
right-to-erasure flow would build on. (A user-facing deletion *endpoint/workflow*
is [FUTURE]; the data model already supports the operation.)

---

## In one sentence

I collect the **rhythm** of computer use — counts, durations, app names, keyed to
an on-device hash of a random id — and I structurally exclude its **content**;
raw granular data lives briefly and close to the device, while clinicians see
longer-lived, lower-risk day-level aggregates.
