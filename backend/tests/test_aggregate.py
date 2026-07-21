import unittest
from datetime import datetime, timezone

from app.aggregate import compute_baseline, compute_daily_metrics, compute_sessions


class AggregateTests(unittest.TestCase):
    def test_documented_score_example_matches_code(self):
        events = [
            {
                "event_type": "active",
                "numeric_value": 180 * 60,
                "ts": datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                "app_name": None,
            },
            {
                "event_type": "app_focus",
                "numeric_value": 800,
                "ts": datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                "app_name": "VS Code",
            },
            {
                "event_type": "app_switch",
                "numeric_value": 3,
                "ts": datetime(2026, 1, 1, 9, tzinfo=timezone.utc),
                "app_name": None,
            },
            {
                "event_type": "keyboard",
                "numeric_value": 47,
                "ts": datetime(2026, 1, 1, 10, tzinfo=timezone.utc),
                "app_name": None,
            },
            {
                "event_type": "mouse",
                "numeric_value": 10,
                "ts": datetime(2026, 1, 1, 11, tzinfo=timezone.utc),
                "app_name": None,
            },
        ]

        self.assertEqual(
            compute_daily_metrics(events),
            {
                "active_minutes": 180,
                "idle_minutes": 0,
                "app_switch_count": 3,
                "focus_score": 73.08,
                "engagement_score": 62.5,
            },
        )

    def test_app_switch_count_comes_from_app_switch_events_not_focus_rows(self):
        ts = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
        events = [
            {"event_type": "active", "numeric_value": 3600, "ts": ts, "app_name": None},
            {"event_type": "app_focus", "numeric_value": 60, "ts": ts, "app_name": "Safari"},
            {"event_type": "app_focus", "numeric_value": 60, "ts": ts, "app_name": "Safari"},
            {"event_type": "app_focus", "numeric_value": 60, "ts": ts, "app_name": "Safari"},
        ]

        self.assertEqual(compute_daily_metrics(events)["app_switch_count"], 0)

    def test_no_activity_does_not_earn_focus_points(self):
        self.assertEqual(
            compute_daily_metrics([]),
            {
                "active_minutes": 0,
                "idle_minutes": 0,
                "app_switch_count": 0,
                "focus_score": 0.0,
                "engagement_score": 0.0,
            },
        )

    def test_keyboard_without_active_span_does_not_create_score(self):
        ts = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
        metrics = compute_daily_metrics([
            {"event_type": "keyboard", "numeric_value": 10, "ts": ts, "app_name": None}
        ])

        self.assertEqual(metrics["active_minutes"], 0)
        self.assertEqual(metrics["focus_score"], 0.0)
        self.assertEqual(metrics["engagement_score"], 0.0)

    def test_sessions_merge_contiguous_active_spans(self):
        events = [
            _active_at("2026-01-01T09:00:00+00:00", 60),
            _active_at("2026-01-01T09:01:00+00:00", 60),
            _active_at("2026-01-01T09:02:30+00:00", 30),
        ]

        sessions = compute_sessions(events)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["duration_sec"], 180)

    def test_sessions_split_after_idle_gap(self):
        events = [
            _active_at("2026-01-01T09:00:00+00:00", 60),
            _active_at("2026-01-01T09:10:30+00:00", 30),
        ]

        sessions = compute_sessions(events)

        self.assertEqual(len(sessions), 2)
        self.assertEqual([s["duration_sec"] for s in sessions], [60, 30])

    def test_baseline_suppresses_alert_with_one_or_two_prior_days(self):
        one_prior = _daily([100, 40])
        two_prior = _daily([100, 100, 40])

        self.assertEqual(compute_baseline(one_prior)["confidence"], "insufficient")
        self.assertFalse(compute_baseline(one_prior)["worth_a_look"])
        self.assertEqual(compute_baseline(two_prior)["confidence"], "insufficient")
        self.assertFalse(compute_baseline(two_prior)["worth_a_look"])

    def test_baseline_suppresses_alert_with_low_confidence_history(self):
        baseline = compute_baseline(_daily([100, 100, 100, 100, 40]))

        self.assertEqual(baseline["confidence"], "low")
        self.assertFalse(baseline["worth_a_look"])
        self.assertIsNone(baseline["alert_threshold_pct"])

    def test_baseline_moderate_confidence_requires_larger_delta(self):
        below_threshold = compute_baseline(_daily([100] * 7 + [51]))
        above_threshold = compute_baseline(_daily([100] * 7 + [49]))

        self.assertEqual(below_threshold["confidence"], "moderate")
        self.assertFalse(below_threshold["worth_a_look"])
        self.assertEqual(below_threshold["alert_threshold_pct"], 50.0)
        self.assertTrue(above_threshold["worth_a_look"])

    def test_baseline_higher_confidence_uses_standard_threshold(self):
        below_threshold = compute_baseline(_daily([100] * 14 + [61]))
        above_threshold = compute_baseline(_daily([100] * 14 + [59]))

        self.assertEqual(below_threshold["confidence"], "higher")
        self.assertFalse(below_threshold["worth_a_look"])
        self.assertEqual(below_threshold["alert_threshold_pct"], 40.0)
        self.assertTrue(above_threshold["worth_a_look"])

def _daily(active_minutes):
    return [
        {"date": f"2026-01-{idx + 1:02d}", "active_minutes": minutes}
        for idx, minutes in enumerate(active_minutes)
    ]


def _active_at(ts, seconds):
    return {
        "event_type": "active",
        "numeric_value": seconds,
        "ts": datetime.fromisoformat(ts),
        "app_name": None,
    }


if __name__ == "__main__":
    unittest.main()
