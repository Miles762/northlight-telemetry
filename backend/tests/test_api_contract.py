import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from app.main import ingest_events
from app.models import MAX_EVENTS_PER_BATCH, EventsBatch


class ApiContractTests(unittest.TestCase):
    def test_rejects_unknown_content_fields_and_window_titles(self):
        payload = {
            "batch_id": str(uuid4()),
            "pseudonym": "subject",
            "events": [
                {
                    "event_type": "keyboard",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "numeric_value": 10,
                    "content": "typed words",
                }
            ],
        }
        with self.assertRaises(ValidationError):
            EventsBatch.model_validate(payload)

        payload["events"][0].pop("content")
        payload["events"][0]["window_title"] = "Private document title"
        with self.assertRaises(ValidationError):
            EventsBatch.model_validate(payload)

    def test_rejects_url_like_app_name(self):
        # app_name is the only free-text field, so it is the one place content
        # could be smuggled. A URL/path/query shape must be rejected.
        ts = datetime.now(timezone.utc).isoformat()
        for smuggled in (
            "https://example.com/private?q=password",
            "http://x",
            "www.example.com",
            "Safari/History?tab=health",
        ):
            payload = {
                "batch_id": str(uuid4()),
                "pseudonym": "subject",
                "events": [
                    {"event_type": "app_focus", "ts": ts, "numeric_value": 60,
                     "app_name": smuggled}
                ],
            }
            with self.assertRaises(ValidationError, msg=f"should reject {smuggled!r}"):
                EventsBatch.model_validate(payload)

    def test_rejects_app_name_on_non_focus_events(self):
        # A plain app display name is fine on app_focus, but app_name riding on a
        # keyboard/active/etc. event is malformed and rejected.
        ts = datetime.now(timezone.utc).isoformat()
        ok = EventsBatch.model_validate({
            "batch_id": str(uuid4()), "pseudonym": "subject",
            "events": [{"event_type": "app_focus", "ts": ts,
                        "numeric_value": 60, "app_name": "Safari"}],
        })
        self.assertEqual(ok.events[0].app_name, "Safari")

        payload = {
            "batch_id": str(uuid4()), "pseudonym": "subject",
            "events": [{"event_type": "keyboard", "ts": ts,
                        "numeric_value": 10, "app_name": "Safari"}],
        }
        with self.assertRaises(ValidationError):
            EventsBatch.model_validate(payload)

    def test_rejects_overlong_or_control_char_app_name(self):
        ts = datetime.now(timezone.utc).isoformat()
        for bad in ("A" * 65, "Sa\nfari", "Slack\t"):
            payload = {
                "batch_id": str(uuid4()), "pseudonym": "subject",
                "events": [{"event_type": "app_focus", "ts": ts,
                            "numeric_value": 60, "app_name": bad}],
            }
            with self.assertRaises(ValidationError, msg=f"should reject {bad!r}"):
                EventsBatch.model_validate(payload)

    def test_rejects_prose_app_name_but_accepts_real_multiword_names(self):
        # app_name is allowlisted to the SHAPE of a real app display name: name
        # charset (letters/digits/spaces + ". - + & ' ( )") and at most a few
        # words. Real names pass; sentences and content-punctuation are rejected.
        ts = datetime.now(timezone.utc).isoformat()
        for legit in ("Safari", "Visual Studio Code", "IntelliJ IDEA CE",
                      "Microsoft Word", "Google Chrome", "Slack",
                      "Adobe Acrobat", "Node.js", "Notes"):
            batch = EventsBatch.model_validate({
                "batch_id": str(uuid4()), "pseudonym": "subject",
                "events": [{"event_type": "app_focus", "ts": ts,
                            "numeric_value": 60, "app_name": legit}],
            })
            self.assertEqual(batch.events[0].app_name, legit)

        # Prose sentences (the exact class an evaluator smuggled through the older
        # denylist): rejected by the 4-word cap and/or the charset allowlist.
        for prose in ("Re layoffs confidential meeting notes about patient",
                      "HIV test results were positive today unfortunately",
                      "call oncologist about biopsy results tomorrow",
                      "meeting with Dr Smith at 3pm",
                      "Re: layoffs",           # colon is not a name character
                      "notes about, the patient"):  # comma is not a name character
            payload = {
                "batch_id": str(uuid4()), "pseudonym": "subject",
                "events": [{"event_type": "app_focus", "ts": ts,
                            "numeric_value": 60, "app_name": prose}],
            }
            with self.assertRaises(ValidationError, msg=f"should reject {prose!r}"):
                EventsBatch.model_validate(payload)

    def test_accepts_controlled_system_signal_types(self):
        ts = datetime.now(timezone.utc).isoformat()
        batch = EventsBatch.model_validate(
            {
                "batch_id": str(uuid4()),
                "pseudonym": "subject",
                "events": [
                    {"event_type": "power_ac", "ts": ts, "numeric_value": 1},
                    {"event_type": "battery_percent", "ts": ts, "numeric_value": 83},
                    {"event_type": "network_connected", "ts": ts, "numeric_value": 1},
                    {"event_type": "display_count", "ts": ts, "numeric_value": 2},
                ],
            }
        )

        self.assertEqual(len(batch.events), 4)

    def test_rejects_oversized_batches_before_db_work(self):
        ts = datetime.now(timezone.utc).isoformat()
        payload = {
            "batch_id": str(uuid4()),
            "pseudonym": "subject",
            "events": [
                {"event_type": "keyboard", "ts": ts, "numeric_value": 1}
                for _ in range(MAX_EVENTS_PER_BATCH + 1)
            ],
        }

        with self.assertRaises(ValidationError):
            EventsBatch.model_validate(payload)

    def test_duplicate_batch_reports_zero_new_insertions(self):
        batch_id = uuid4()
        batch = EventsBatch.model_validate(
            {
                "batch_id": str(batch_id),
                "pseudonym": "subject",
                "events": [
                    {
                        "event_type": "keyboard",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "numeric_value": 10,
                    }
                ],
            }
        )
        cursor = DuplicateBatchCursor(str(batch_id))

        @contextmanager
        def fake_get_conn():
            yield FakeConnection(cursor)

        with patch("app.main.get_conn", fake_get_conn):
            result = ingest_events(batch)

        self.assertEqual(result.inserted_events, 0)
        self.assertEqual(result.days_aggregated, [])
        self.assertFalse(cursor.inserted_raw_events)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class DuplicateBatchCursor:
    def __init__(self, batch_id):
        self.batch_id = batch_id
        self._last_query = ""
        self.inserted_raw_events = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self._last_query = " ".join(query.split())
        if self._last_query.startswith("INSERT INTO telemetry_events"):
            self.inserted_raw_events = True

    def executemany(self, query, params=None):
        self._last_query = " ".join(query.split())
        if self._last_query.startswith("INSERT INTO telemetry_events"):
            self.inserted_raw_events = True

    def fetchone(self):
        if self._last_query.startswith("SELECT id FROM users"):
            return {"id": "00000000-0000-0000-0000-000000000001"}
        if self._last_query.startswith("SELECT event_count FROM ingest_batches"):
            return {"event_count": 1}
        return None


if __name__ == "__main__":
    unittest.main()
