// Formatting helpers. Numbers are shown with the precision the data supports — no more.

export function combinedOdds(odds: (number | null | undefined)[]): number | null {
  if (!odds.length) return null;
  let p = 1;
  for (const o of odds) {
    if (o == null || !(o > 1)) return null;
    p *= o;
  }
  return p;
}

export const fmtOdds = (o: number | null | undefined) => (o == null ? "—" : o.toFixed(2));
export const pct = (x: number | null | undefined, digits = 0) => (x == null ? "—" : `${(100 * x).toFixed(digits)}%`);
export const pctInt = (x: number | null | undefined) => (x == null ? "—" : `${x}%`);
export const num = (x: number | null | undefined, digits = 2) => (x == null ? "—" : x.toFixed(digits));

export function smallPct(x: number | null | undefined): string {
  if (x == null) return "—";
  const v = 100 * x;
  if (v >= 10) return `${v.toFixed(0)}%`;
  if (v >= 1) return `${v.toFixed(1)}%`;
  return `${v.toFixed(2)}%`;
}

export function hr(h: { k: number; n: number } | null | undefined): string {
  if (!h || !h.n) return "no data";
  return `${h.k}/${h.n}`;
}

export const ZONE = "Europe/Belgrade";

export function todayLocal(zone = ZONE): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(),
  );
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function weekday(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

export function utcToLocal(isoUtc: string | null | undefined, zone = ZONE): string {
  if (!isoUtc) return "—";
  const d = new Date(isoUtc);
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
    .format(d)
    .replace(",", "");
}

export function nowLocalInput(zone = ZONE): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const g = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${g("year")}-${g("month")}-${g("day")} ${g("hour") === "24" ? "00" : g("hour")}:${g("minute")}`;
}

export const STATUS_TONE: Record<string, string> = {
  candidate: "good",
  flagged: "warn",
  rejected: "bad",
  ineligible: "muted",
  strong: "good",
  acceptable: "info",
  weak: "warn",
  high: "good",
  medium: "info",
  low: "warn",
  none: "muted",
  won: "good",
  half_won: "good",
  lost: "bad",
  half_lost: "bad",
  void: "muted",
  pending: "info",
};

export const RISK_TONE: Record<string, string> = { low: "good", medium: "warn", high: "bad" };

export const TIME_LABEL: Record<string, string> = {
  corroborated: "time corroborated",
  single_source: "single source",
  uncertain: "time ±1h?",
  unknown: "time unknown",
  conflict: "time conflict",
  user_corrected: "time set by you",
};
