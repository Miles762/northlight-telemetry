import { useEffect, useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, BarChart, Bar,
} from "recharts";
import { fetchDashboard, type DashboardData, type DailyMetric } from "./api";

// Recharts writes stroke/fill straight onto SVG attributes, where CSS custom
// properties (var(--x)) do not reliably resolve. So we read the palette roles
// from the document once into concrete hex, then hand Recharts real colors.
// Re-read on OS light/dark change so charts follow the theme.
function readPalette() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    s1: v("--series-1"), s2: v("--series-2"), s3: v("--series-3"),
    grid: v("--grid"), baseline: v("--baseline"),
    muted: v("--text-muted"), secondary: v("--text-secondary"),
    surface: v("--surface-1"), border: v("--baseline"), primary: v("--text-primary"),
  };
}
type Palette = ReturnType<typeof readPalette>;

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pal, setPal] = useState<Palette>(() => readPalette());

  useEffect(() => {
    fetchDashboard()
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
    // Follow OS theme changes so chart colors re-resolve.
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setPal(readPalette());
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return (
    <div className="min-h-full" style={{ background: "var(--page)" }}>
      <Header pseudonym={data?.pseudonym} />

      <main className="mx-auto max-w-5xl px-4 pb-16">
        {error && <Notice text={`Could not load data: ${error}. Is the backend running on :8000?`} />}
        {!data && !error && <Notice text="Loading…" />}
        {data && data.daily_metrics.length === 0 && (
          <Notice text="No telemetry yet. Start the agent (or run the synthetic generator) and refresh." />
        )}

        {data && data.summary && (
          <>
            <SummaryTiles day={data.summary} />
            <div className="grid gap-4 md:grid-cols-2 mt-4">
              <Card title="Active vs idle" subtitle="Proportion of the latest day">
                <ActiveIdle day={data.summary} />
              </Card>
              <Card title="Application usage" subtitle="Time in focus by app · names only">
                <AppUsageChart usage={data.app_usage} pal={pal} />
              </Card>
              <Card title="Day timeline" subtitle="Active / idle spans & system markers across the day">
                <Timeline entries={data.timeline} />
              </Card>
              <Card title="Baseline comparison" subtitle="Latest day vs this person's own trailing mean">
                <BaselinePanel data={data} />
              </Card>
            </div>
            <div className="grid gap-4 md:grid-cols-2 mt-4">
              <Card title="Score trends" subtitle="Focus · engagement (0–100) across collected days">
                <ScoreTrends daily={data.daily_metrics} pal={pal} />
              </Card>
              <Card title="Active-minutes trend" subtitle="Active time per day (minutes)">
                <ActiveTrend daily={data.daily_metrics} pal={pal} />
              </Card>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

/* ---------------------------------------------------------------- header --- */
// The "signal, not diagnosis" framing is persistent (PRD §9.4): it lives in the
// header, visible on every render, not a dismissible toast.
function Header({ pseudonym }: { pseudonym?: string }) {
  return (
    <header className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
      <div className="mx-auto max-w-5xl px-4 py-4">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <h1 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
            NorthLight · Clinician Dashboard
          </h1>
          {pseudonym && (
            <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
              subject {pseudonym.slice(0, 12)}…
            </span>
          )}
        </div>
        <p
          role="note"
          className="mt-2 text-sm rounded px-3 py-2"
          style={{
            color: "var(--text-secondary)",
            background: "color-mix(in srgb, var(--warning) 12%, transparent)",
            border: "1px solid var(--border)",
          }}
        >
          These metrics represent behavioral signals and should not be interpreted as diagnoses.
        </p>
      </div>
    </header>
  );
}

/* ------------------------------------------------------------- summary ----- */
function SummaryTiles({ day }: { day: DailyMetric }) {
  const tiles = [
    { label: "Focus score", value: fmt(day.focus_score), hint: "0–100" },
    { label: "Engagement score", value: fmt(day.engagement_score), hint: "0–100" },
    { label: "Active time", value: `${day.active_minutes}m`, hint: "" },
    { label: "Idle time", value: `${day.idle_minutes}m`, hint: "" },
    { label: "App switches", value: `${day.app_switch_count}`, hint: "fragmentation" },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mt-4">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-lg px-4 py-3"
             style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>{t.label}</div>
          <div className="text-2xl font-semibold mt-1" style={{ color: "var(--text-primary)" }}>
            {t.value}
          </div>
          {t.hint && <div className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>{t.hint}</div>}
        </div>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- charts ---- */
function ActiveIdle({ day }: { day: DailyMetric }) {
  // A single proportional bar: active vs idle. Idle uses neutral gray (absence,
  // not an identity). Direct labels because these two fills carry the meaning.
  const total = Math.max(day.active_minutes + day.idle_minutes, 1);
  const activePct = Math.round((day.active_minutes / total) * 100);
  return (
    <div className="pt-2">
      <div className="flex h-8 w-full overflow-hidden rounded" style={{ background: "var(--grid)" }}>
        <div style={{ width: `${activePct}%`, background: "var(--series-1)" }}
             className="flex items-center justify-center text-xs font-medium text-white" >
          {activePct >= 12 ? `Active ${activePct}%` : ""}
        </div>
        <div style={{ width: `${100 - activePct}%`, background: "var(--series-idle)" }}
             className="flex items-center justify-center text-xs font-medium text-white">
          {100 - activePct >= 12 ? `Idle ${100 - activePct}%` : ""}
        </div>
      </div>
      <div className="flex gap-4 mt-3 text-xs" style={{ color: "var(--text-secondary)" }}>
        <LegendDot color="var(--series-1)" label={`Active · ${day.active_minutes}m`} />
        <LegendDot color="var(--series-idle)" label={`Idle · ${day.idle_minutes}m`} />
      </div>
    </div>
  );
}

function AppUsageChart({ usage, pal }: { usage: DashboardData["app_usage"]; pal: Palette }) {
  if (!usage.length) return <Empty text="No app-focus data for this day." />;
  const rows = usage.slice(0, 8); // top apps; a 9th+ folds away (never cycle hues)
  return (
    <ResponsiveContainer width="100%" height={Math.max(rows.length * 44, 132)}>
      <BarChart data={rows} layout="vertical" barCategoryGap="20%"
                margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
        <CartesianGrid horizontal={false} stroke={pal.grid} />
        <XAxis type="number" dataKey="minutes" tick={{ fill: pal.muted, fontSize: 11 }}
               stroke={pal.baseline} unit="m" />
        <YAxis type="category" dataKey="app_name" width={96}
               tick={{ fill: pal.secondary, fontSize: 12 }} stroke={pal.baseline} />
        <Tooltip {...tooltip(pal)} formatter={(v) => [`${v} min`, "in focus"]} />
        <Bar isAnimationActive={false} dataKey="minutes" fill={pal.s1} radius={[0, 4, 4, 0]} maxBarSize={22} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function Timeline({ entries }: { entries: DashboardData["timeline"] }) {
  if (!entries.length) return <Empty text="No timeline events for this day." />;
  // Coarse strip: active/idle spans sized by duration, in clock order, with
  // session/system markers. Duration/state + type only — no content.
  return (
    <div className="pt-2">
      <div className="flex w-full h-8 overflow-hidden rounded" style={{ background: "var(--grid)" }}>
        {entries.map((e, i) => {
          const isSpan = e.event_type === "active" || e.event_type === "idle";
          const flex = isSpan ? Math.max(e.seconds, 1) : 0;
          const color =
            e.event_type === "active" ? "var(--series-1)" :
            e.event_type === "idle" ? "var(--series-idle)" : "transparent";
          if (!isSpan) {
            return <div key={i} title={`${markerTitle(e)} @ ${e.clock}`}
                        style={{ width: 3, background: "var(--serious)" }} />;
          }
          return <div key={i} title={`${e.event_type} ${Math.round(e.seconds)}s @ ${e.clock}`}
                      style={{ flexGrow: flex, background: color }} />;
        })}
      </div>
      <div className="flex flex-wrap gap-4 mt-3 text-xs" style={{ color: "var(--text-secondary)" }}>
        <LegendDot color="var(--series-1)" label="Active" />
        <LegendDot color="var(--series-idle)" label="Idle" />
        <LegendDot color="var(--serious)" label="Session / system marker" />
      </div>
    </div>
  );
}

// Scores and active-minutes are split into two charts on purpose: a 0–100 score
// scale and a 0–300+ minute scale share no common axis, and forcing them onto
// one crushes the scores against the baseline. One measure per y-axis.
function ScoreTrends({ daily, pal }: { daily: DailyMetric[]; pal: Palette }) {
  if (daily.length < 1) return <Empty text="No days collected yet." />;
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={daily} margin={{ left: 4, right: 16, top: 8, bottom: 4 }}>
        <CartesianGrid stroke={pal.grid} vertical={false} />
        <XAxis dataKey="date" tick={{ fill: pal.muted, fontSize: 11 }} stroke={pal.baseline} />
        <YAxis domain={[0, 100]} tick={{ fill: pal.muted, fontSize: 11 }} stroke={pal.baseline} />
        <Tooltip {...tooltip(pal)} />
        <Legend wrapperStyle={{ fontSize: 12, color: pal.secondary }} />
        <Line isAnimationActive={false} type="monotone" dataKey="focus_score" name="Focus"
              stroke={pal.s1} strokeWidth={2} dot={{ r: 3, fill: pal.s1 }} />
        <Line isAnimationActive={false} type="monotone" dataKey="engagement_score" name="Engagement"
              stroke={pal.s2} strokeWidth={2} dot={{ r: 3, fill: pal.s2 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function ActiveTrend({ daily, pal }: { daily: DailyMetric[]; pal: Palette }) {
  if (daily.length < 1) return <Empty text="No days collected yet." />;
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={daily} margin={{ left: 4, right: 16, top: 8, bottom: 4 }}>
        <CartesianGrid stroke={pal.grid} vertical={false} />
        <XAxis dataKey="date" tick={{ fill: pal.muted, fontSize: 11 }} stroke={pal.baseline} />
        <YAxis tick={{ fill: pal.muted, fontSize: 11 }} stroke={pal.baseline} unit="m" />
        <Tooltip {...tooltip(pal)} formatter={(v) => [`${v} min`, "active"]} />
        <Line isAnimationActive={false} type="monotone" dataKey="active_minutes" name="Active min"
              stroke={pal.s3} strokeWidth={2} dot={{ r: 3, fill: pal.s3 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function BaselinePanel({ data }: { data: DashboardData }) {
  const b = data.baseline;
  if (!b) return <Empty text="Baseline needs at least two collected days." />;
  const up = b.delta_active_pct >= 0;
  const canAlert = b.confidence === "moderate" || b.confidence === "higher";
  return (
    <div className="pt-1">
      <div className="flex items-start justify-between gap-3">
        <div className="text-3xl font-semibold" style={{ color: up ? "var(--delta-good)" : "var(--serious)" }}>
          {up ? "▲" : "▼"} {Math.abs(b.delta_active_pct)}%
        </div>
        <span
          className="rounded px-2 py-1 text-xs font-medium capitalize"
          style={{ color: "var(--text-secondary)", background: "var(--grid)" }}
        >
          {b.confidence} confidence
        </span>
      </div>
      <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
        Latest active time <strong>{b.latest_active_minutes}m</strong> vs trailing mean{" "}
        <strong>{b.trailing_mean_active_minutes}m</strong> over {b.trailing_days} prior day
        {b.trailing_days === 1 ? "" : "s"}.
      </p>
      <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
        {b.reason}
      </p>
      {!canAlert && (
        <div className="mt-3 text-sm rounded px-3 py-2"
             style={{ color: "var(--text-secondary)", background: "color-mix(in srgb, var(--warning) 12%, transparent)", border: "1px solid var(--border)" }}>
          More days are needed before surfacing a trend alert from passive activity data.
        </div>
      )}
      {b.worth_a_look && (
        <div className="mt-3 flex items-start gap-2 text-sm rounded px-3 py-2"
             style={{ color: "var(--text-primary)", background: "color-mix(in srgb, var(--serious) 14%, transparent)", border: "1px solid var(--border)" }}>
          <span aria-hidden>⚑</span>
          <span>Worth a look — activity differs notably from this person's own baseline. A prompt to check in, not an abnormality.</span>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- helpers ----- */
function Card({ title, subtitle, children, className = "" }:
  { title: string; subtitle?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg p-4 ${className}`}
             style={{ background: "var(--surface-1)", border: "1px solid var(--border)" }}>
      <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{title}</h2>
      {subtitle && <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>{subtitle}</p>}
      {children}
    </section>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

function Notice({ text }: { text: string }) {
  return <div className="mt-6 text-sm rounded px-4 py-3"
              style={{ color: "var(--text-secondary)", background: "var(--surface-1)", border: "1px solid var(--border)" }}>{text}</div>;
}
function Empty({ text }: { text: string }) {
  return <div className="py-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>{text}</div>;
}

function tooltip(pal: Palette) {
  return {
    contentStyle: {
      background: pal.surface, border: `1px solid ${pal.border}`,
      borderRadius: 8, color: pal.primary, fontSize: 12,
    },
    labelStyle: { color: pal.secondary },
  };
}

const fmt = (n: number | null) => (n == null ? "—" : n.toFixed(1));

function markerTitle(e: DashboardData["timeline"][number]) {
  switch (e.event_type) {
    case "power_ac": return `AC power ${e.seconds ? "connected" : "disconnected"}`;
    case "battery_percent": return `Battery ${Math.round(e.seconds)}%`;
    case "network_connected": return `Network ${e.seconds ? "connected" : "disconnected"}`;
    case "display_count": return `${Math.round(e.seconds)} display(s)`;
    default: return e.event_type;
  }
}
