"""Request/response contracts for the two endpoints (PRD §8).

The ingest model is where the content-exclusion boundary is enforced on the
server side, in two layers:
  1. `model_config = extra="forbid"` rejects a batch carrying any field we did
     not explicitly allow (a stray "text", "keys", "url", "content"...) -- so
     content named as content is turned away outright.
  2. The only free-text field, `app_name`, is validated to be *app identity
     only* (short, no control chars, no URL/path/query shapes, and only on
     app_focus events) -- so content cannot ride in disguised as an app name.
Together these mean the store holds application display names and numeric
counts/durations, and nothing content-shaped can be persisted through the API.
"""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_EVENTS_PER_BATCH = 500

# app_name is the only free-text field, so it is the one place a hostile or buggy
# client could try to smuggle content (a URL, a window title) into the store.
# extra="forbid" stops fields *named* url/text/content; these rules stop content
# *shaped* like app identity from riding in through app_name. app_name carries an
# application's display name (e.g. "Safari") -- never a URL, path, or title.
MAX_APP_NAME_LEN = 80
# Substrings that indicate a URL/path/query rather than an app display name.
_CONTENT_MARKERS = ("://", "http", "www.", "/", "?", "&", "=")

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
        # No control characters / newlines (an app display name has none).
        if any(ord(ch) < 32 for ch in name):
            raise ValueError("app_name contains control characters")
        # No URL/path/query shapes -- those are content, not an app identity.
        lowered = name.lower()
        if any(marker in lowered for marker in _CONTENT_MARKERS):
            raise ValueError("app_name looks like a URL/path, not an app name")
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
