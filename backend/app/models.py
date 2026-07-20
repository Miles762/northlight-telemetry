"""Request/response contracts for the two endpoints (PRD §8).

The ingest model is where the content-exclusion boundary is enforced on the
server side: `model_config = extra="forbid"` means a batch carrying any field
we did not explicitly allow (a stray "text", "keys", "url", "content"...) is
rejected outright (PRD §8.1: "rejects anything carrying unexpected content
fields"). The only text fields that exist are `app_name` and the opt-in
`window_title` -- there is no field an agent could use to smuggle content.
"""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
]


class EventIn(BaseModel):
    """A single privacy-safe observation from the agent.

    No content fields exist here by construction. `numeric_value` is a count or
    a duration in seconds depending on `event_type`; `app_name`/`window_title`
    are app/window identity only.
    """

    model_config = ConfigDict(extra="forbid")  # reject unknown -> content can't sneak in

    event_type: EventType
    ts: datetime
    numeric_value: Optional[float] = None
    app_name: Optional[str] = None
    window_title: Optional[str] = None  # opt-in, sensitive; agent leaves it None by default


class EventsBatch(BaseModel):
    """The POST /events payload: who sent it (pseudonym) and the events.

    `pseudonym` is the hashed local install id (PRD §11.4). The backend maps it
    to a users row (creating one on first sight) -- the raw identifier that
    produced the hash never reaches this server.
    """

    model_config = ConfigDict(extra="forbid")

    # Client-generated per batch, reused on retries. The dedup key that makes a
    # retried POST a no-op (PRD §4 NFR; migration 0003). One id per batch, since
    # the agent sends a batch atomically.
    batch_id: UUID
    pseudonym: str = Field(min_length=1)
    events: list[EventIn]


class IngestResult(BaseModel):
    inserted_events: int
    days_aggregated: list[str]  # ISO dates whose daily_metrics were recomputed
