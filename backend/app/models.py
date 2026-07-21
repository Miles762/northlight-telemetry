"""Request/response contracts for the two endpoints (PRD §8).

The content-exclusion boundary is enforced primarily AT CAPTURE, in the agent:
the input monitors discard the OS event payload and only increment a count, and
the foreground signal reads NSRunningApplication.localizedName -- an app identity
by construction (see Telemetry.swift). The server never receives content because
the agent never sends it.

This ingest model is the server-side DEFENSE-IN-DEPTH against a hostile or buggy
client, in two layers:
  1. `model_config = extra="forbid"` rejects a batch carrying any field we did
     not explicitly allow (a stray "text", "keys", "url", "content"...) -- so
     content named as content is turned away outright.
  2. The only free-text field, `app_name`, is allowlisted to the *shape* of a
     real app display name (short, name-charset only, few words, app_focus events
     only) -- so URLs, paths, and prose sentences are rejected.
Honest limit: the server cannot tell a one-word app name ("Slack") from a
one-word secret ("hunter2") by string inspection, so this layer rejects
content-*shaped* input, not every conceivable string. The guarantee that only
app identities arrive comes from the agent, not from this validator.
"""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_EVENTS_PER_BATCH = 500

# app_name is the only free-text field, so it is the one place a hostile or buggy
# client could try to smuggle content (a URL, a window title, a sentence) into the
# store. This validator is DEFENSE-IN-DEPTH, not the primary guarantee: the real
# guarantee is that the agent only ever sends NSRunningApplication.localizedName
# (see Telemetry.swift), which is an app identity by construction. The server
# cannot perfectly tell a one-word app name ("Slack") from a one-word secret
# ("hunter2") by inspection -- so instead of a denylist that tries to enumerate
# bad content (which leaks: a clean sentence has no URL markers), we ALLOWLIST the
# shape of a real macOS app display name and reject everything else.
MAX_APP_NAME_LEN = 64
# A real app display name is a short handful of words: "Visual Studio Code",
# "IntelliJ IDEA CE", "Microsoft Word". Four is a real ceiling above observed
# names; a 5+ word string is prose ("call oncologist about biopsy results
# tomorrow"), not an app identity.
MAX_APP_NAME_WORDS = 4
# The characters a real app display name is built from: letters (any script),
# digits, spaces, and the few punctuation marks that appear in product names
# (". - + & ' ( )"). Anything outside this set -- ":", "/", "?", "#", ",", ";",
# quotes, @, etc. -- is a shape a legitimate app name does not take, so it is
# rejected. This allowlist is what stops sentences/URLs/titles, rather than a
# denylist of markers we would have to keep guessing at.
_APP_NAME_PUNCT = set(" .-+&'()")
# One residual case the charset allowlist admits: a bare domain like
# "www.example.com" is charset-clean (letters + dots). A real dotted app name has
# a single short suffix ("Node.js"); a domain has multiple dot-joined labels. We
# reject any name with 2+ dots or a leading "www." -- the domain shape -- while
# still allowing one dot for names like Node.js.
_URL_HINTS = ("://", "www.")

# The closed set of event types the agent may send (PRD §5). Anything else is a
# 422. Keeping this an explicit Literal is the server-side counterpart to the
# migration's deliberately-unconstrained event_type column: the DB stays
# flexible, the API is strict.
EventType = Literal[
    "keyboard",   # count of keyboard events in a bucket -- COUNT ONLY, never keys
    "mouse",      # count of mouse events (clicks+scrolls) in a bucket
    "app_focus",  # time in focus for an app; app_name set, numeric_value = focus seconds
    "app_switch", # count of REAL foreground-app changes in a bucket (fragmentation signal)
    "active",     # an active span began (session open)
    "idle",       # went idle (session close)
    "lock",       # screen locked (session close)
    "unlock",     # screen unlocked (session open)
    "sleep",      # machine slept (session close)
    "wake",       # machine woke (session open)
    "power_ac",   # 1 if AC adapter/external power present, else 0
    "battery_percent",   # current battery percentage, if available
    "network_connected", # 1 if any network path is satisfied, else 0; no SSID/IP
    "display_count",     # number of attached displays; no names/serials/contents
]


class EventIn(BaseModel):
    """A single privacy-safe observation from the agent.

    No content fields exist here by construction. `numeric_value` is a count or
    a duration in seconds depending on `event_type`; `app_name` is application
    identity only.
    """

    model_config = ConfigDict(extra="forbid")  # reject unknown -> content can't sneak in

    event_type: EventType
    ts: datetime
    numeric_value: Optional[float] = None
    app_name: Optional[str] = None

    @model_validator(mode="after")
    def _app_name_is_identity_only(self) -> "EventIn":
        name = self.app_name
        if name is None:
            return self
        # app_name belongs only to app_focus events. Seeing it anywhere else is a
        # malformed/suspicious payload, not a normal agent message.
        if self.event_type != "app_focus":
            raise ValueError("app_name is only allowed on app_focus events")
        if len(name) > MAX_APP_NAME_LEN:
            raise ValueError(f"app_name exceeds {MAX_APP_NAME_LEN} chars")
        # Allowlist the shape of a real app display name: every character must be a
        # letter, a digit, or one of the few name-punctuation marks. This rejects
        # URLs, paths, and any sentence carrying ":", ",", quotes, "@", etc. -- and
        # it does so without trying to enumerate every bad substring.
        for ch in name:
            if not (ch.isalnum() or ch in _APP_NAME_PUNCT):
                raise ValueError("app_name contains characters not seen in app names")
        # Even within that charset, prose sneaks through as space-separated words.
        # A real app name is a short handful of words; 5+ is a sentence, not an
        # identity ("call oncologist about biopsy results tomorrow").
        if len(name.split()) > MAX_APP_NAME_WORDS:
            raise ValueError("app_name has too many words to be an app name")
        # A bare domain ("www.example.com") is charset-clean but is a URL, not an
        # app name: reject the domain shape (leading "www.", a scheme, or 2+ dots).
        lowered = name.lower()
        if any(hint in lowered for hint in _URL_HINTS) or name.count(".") >= 2:
            raise ValueError("app_name looks like a domain/URL, not an app name")
        return self


class EventsBatch(BaseModel):
    """The POST /events payload: who sent it (pseudonym) and the events.

    `pseudonym` is the hashed local install id (PRD §11.4). The backend maps it
    to a users row (creating one on first sight) -- the raw identifier that
    produced the hash never reaches this server.
    """

    model_config = ConfigDict(extra="forbid")

    # Client-generated per batch, reused on retries. The dedup key that makes a
    # retried POST a no-op (PRD §4 NFR; migration 0003). The event list is capped
    # so one request cannot force an unbounded executemany() transaction.
    batch_id: UUID
    pseudonym: str = Field(min_length=1)
    events: list[EventIn] = Field(min_length=1, max_length=MAX_EVENTS_PER_BATCH)


class IngestResult(BaseModel):
    inserted_events: int
    days_aggregated: list[str]  # ISO dates whose daily_metrics were recomputed
