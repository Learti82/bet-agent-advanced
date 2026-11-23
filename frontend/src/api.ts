// Thin typed client for the local FastAPI backend. Everything stays on this machine.

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function messageFrom(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? JSON.stringify(d)).join("; ");
  if (detail && typeof detail === "object") {
    const d = detail as { message?: string; errors?: string[] };
    return [d.message, ...(d.errors ?? [])].filter(Boolean).join(" — ");
  }
  return "Request failed";
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const opts: RequestInit = { ...init };
  if (init?.json !== undefined) {
    opts.body = JSON.stringify(init.json);
    opts.headers = { "Content-Type": "application/json", ...(init.headers ?? {}) };
  }
  const res = await fetch(path, opts);
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail ?? data;
    throw new ApiError(res.status, messageFrom(detail), detail);
  }
  return data as T;
}

export const enc = (id: string) => encodeURIComponent(id);
export const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
};

// ---------------------------------------------------------------- types
export interface Price {
  id: number;
  bookmaker: string;
  odds: number;
  source: "manual" | "dataset_snapshot";
  checked_at: string;
  line: number | null;
  market: string;
  selection: string;
  note?: string | null;
}

export interface Fixture {
  id: string;
  competition: string;
  competition_name: string;
  country: string | null;
  kind: string | null;
  date: string;
  home: string;
  away: string;
  home_id: string;
  away_id: string;
  kickoff_utc: string | null;
  kickoff_local: string | null;
  local_date: string;
  timezone: string;
  time_certainty: string;
  time_notes: string[];
  status: string;
  dataset_status: string;
  prematch_eligible: boolean;
  prematch_status: string;
  verified: boolean;
  verification_url: string | null;
  override_note: string | null;
  score: string | null;
  manual_odds: number;
  snapshot_odds: number;
  research_count: number;
  source: string;
}

export interface HitRate {
  k: number;
  n: number;
  of: number;
  rate: number | null;
}

export interface Candidate {
  key: string;
  market: string;
  market_name: string;
  family: string;
  selection: string;
  line: number | null;
  label: string;
  supported: boolean;
  unsupported_reason: string | null;
  probability: number | null;
  probability_pct: number | null;
  range_pct: [number, number] | null;
  probability_source: string | null;
  hit_rates: { home_team_home: HitRate; away_team_away: HitRate; home_team_last10: HitRate; away_team_last10: HitRate };
  price: Price | null;
  prices: Price[];
  implied_probability: number | null;
  fair_probability: number | null;
  overround: number | null;
  edge: number | null;
  expected_value: number | null;
  accumulator_ok: boolean;
  flags: string[];
  research: { id: number; impact: string; reliability: string; statistic: string | null; url: string | null }[];
  score: {
    components: Record<string, number>;
    adjustments: { reason: string; points: number }[];
    evidence: number;
    total: number;
    flags: string[];
    hit_sample: number;
  };
  gates_failed: string[];
  qualifies: boolean;
  needs_price: boolean;
  tier: "strong" | "acceptable" | "weak";
  confidence: "high" | "medium" | "low" | "none";
  win_probability: number | null;
  void_probability: number;
}

export interface Factor {
  code: string;
  severity: "low" | "medium" | "high";
  action: "reject" | "flag" | "info";
  message: string;
}

export interface Brief {
  key: string;
  label: string;
  market: string;
  market_name: string;
  family: string;
  probability_pct: number | null;
  range_pct: [number, number] | null;
  price: Price | null;
  implied_probability: number | null;
  edge: number | null;
  tier: string;
  qualifies: boolean;
  needs_price: boolean;
  score: number;
  evidence: number;
  confidence: string;
}

export interface Summary {
  fixture: Fixture;
  status: "candidate" | "flagged" | "rejected" | "ineligible";
  reasons: string[];
  factors: Factor[];
  recommendation: Brief | null;
  qualifying: Brief[];
  research_score: number;
  data_quality: number;
  data_quality_label: string;
  risk_level: string;
  expected_goals: { home: number; away: number; total: number } | null;
  missing_information: string[];
  alternatives: string[];
}

export interface Leg {
  match_id: string;
  key: string;
  label: string;
  match_label: string;
  competition: string;
  competition_name: string;
  kickoff_local: string | null;
  local_date: string;
  odds: number | null;
  bookmaker: string | null;
  odds_source: string | null;
  odds_checked_at: string | null;
  probability: number | null;
  probability_pct: number | null;
  range_pct: [number, number] | null;
  score: number;
  tier: string;
  confidence: string | null;
  qualifies: boolean;
  data_quality: number;
  match_status: string;
  family: string;
}

export interface TicketEvaluation {
  n_selections: number;
  combined_odds: number | null;
  target_odds: number | null;
  target_reached: boolean | null;
  bookmaker_implied_probability: number | null;
  model_probability_all_win: number | null;
  model_probability_no_loss: number | null;
  model_probability_note: string;
  weak_legs: number;
  errors: string[];
  warnings: string[];
  correlations: { type: string; strength: string; legs: string[]; note: string; match_label?: string }[];
  valid: boolean;
  price_sources: string[];
}

export interface Status {
  app: string;
  now_local: string;
  timezone: string;
  bookmaker: string;
  dataset: null | {
    generated_utc: string | null;
    age_days: number | null;
    imported_at: string;
    method: string;
    commit_sha: string | null;
    results: number;
    fixtures: number;
    competitions: number;
  };
  counts: Record<string, number>;
  ai: { enabled: boolean; model: string };
  warnings: string[];
  attribution: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Analysis = any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Report = any;
