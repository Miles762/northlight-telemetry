// Typed data contract for GET /dashboard, mirroring backend/app/main.py exactly.
// The dashboard is read-only (PRD §9): this is the only network call it makes.

export interface DailyMetric {
  date: string; // ISO date
  active_minutes: number;
  idle_minutes: number;
  app_switch_count: number;
  focus_score: number | null;
  engagement_score: number | null;
}

export interface AppUsage {
  app_name: string; // app NAME only — never a window title or URL (PRD §5.4)
  minutes: number;
}

export interface TimelineEntry {
  event_type:
    | "active"
    | "idle"
    | "lock"
    | "unlock"
    | "sleep"
    | "wake"
    | "power_ac"
    | "battery_percent"
    | "network_connected"
    | "display_count";
  clock: string; // "HH:MM"
  seconds: number;
}

export interface Baseline {
  trailing_days: number;
  trailing_mean_active_minutes: number;
  latest_active_minutes: number;
  delta_active_pct: number;
  worth_a_look: boolean;
  confidence: "insufficient" | "low" | "moderate" | "higher";
  alert_threshold_pct: number | null;
  reason: string;
}

export interface DashboardData {
  pseudonym: string;
  daily_metrics: DailyMetric[];
  summary: DailyMetric | null;
  app_usage: AppUsage[];
  timeline: TimelineEntry[];
  baseline: Baseline | null;
}

// Backend base URL. Localhost only — the whole slice runs on one machine (§4).
const BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

// A just-started backend can briefly refuse connections or 404 before its
// routes finish registering. Rather than surface that transient startup state
// as a hard error to a clinician, retry a few times with a short backoff; only
// a failure that persists past that window is shown. This does not mask a real
// outage — after the retries, the same clear error is thrown.
export async function fetchDashboard(
  pseudonym?: string,
  { retries = 8, delayMs = 1000 }: { retries?: number; delayMs?: number } = {},
): Promise<DashboardData> {
  const url = new URL("/dashboard", BASE);
  if (pseudonym) url.searchParams.set("pseudonym", pseudonym);

  let lastError = "";
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url.toString());
      if (res.ok) return res.json();
      // 5xx / 404-while-warming-up are worth retrying; 4xx like a bad
      // pseudonym are not — but here the only 4xx is a not-yet-ready route,
      // so we retry those too and let the final throw report the status.
      lastError = `GET /dashboard failed: ${res.status}`;
    } catch (e) {
      // fetch() throws on connection refused — the backend isn't up yet.
      lastError = e instanceof Error ? e.message : "backend unreachable";
    }
    if (attempt < retries) await new Promise((r) => setTimeout(r, delayMs));
  }
  throw new Error(lastError);
}
