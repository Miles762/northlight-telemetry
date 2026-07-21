import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("dashboard has no serious automated accessibility violations", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/dashboard", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        pseudonym: "synthetic-a11y-001",
        daily_metrics: [
          {
            date: "2026-07-18",
            active_minutes: 180,
            idle_minutes: 30,
            app_switch_count: 8,
            focus_score: 72.5,
            engagement_score: 68.2,
          },
          {
            date: "2026-07-19",
            active_minutes: 220,
            idle_minutes: 20,
            app_switch_count: 6,
            focus_score: 78.1,
            engagement_score: 74.4,
          },
        ],
        summary: {
          date: "2026-07-19",
          active_minutes: 220,
          idle_minutes: 20,
          app_switch_count: 6,
          focus_score: 78.1,
          engagement_score: 74.4,
        },
        app_usage: [
          { app_name: "VS Code", minutes: 90 },
          { app_name: "Safari", minutes: 45 },
        ],
        timeline: [
          { event_type: "unlock", clock: "09:00", seconds: 0 },
          { event_type: "active", clock: "09:00", seconds: 3600 },
          { event_type: "battery_percent", clock: "09:00", seconds: 82 },
          { event_type: "idle", clock: "10:00", seconds: 600 },
        ],
        baseline: {
          trailing_days: 1,
          trailing_mean_active_minutes: 180,
          latest_active_minutes: 220,
          delta_active_pct: 22.2,
          worth_a_look: false,
          confidence: "insufficient",
          alert_threshold_pct: null,
          reason: "Needs at least 3 prior days before judging whether this differs from baseline.",
        },
      }),
    });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /northlight/i })).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  const seriousOrCritical = results.violations.filter((violation) => {
    return violation.impact === "serious" || violation.impact === "critical";
  });

  expect(seriousOrCritical).toEqual([]);
});
