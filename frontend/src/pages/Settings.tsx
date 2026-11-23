import { useEffect, useState } from "react";
import { api } from "../api";
import { useStatus } from "../App";
import { Chip, ErrorBox, Loading, Panel, useFetch } from "../components/ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
type G = Record<string, any>;

const GROUPS: [string, string, [string, string][]][] = [
  ["General", "", [["timezone", "Display timezone (IANA)."], ["bookmaker", "Preferred bookmaker; its manual prices are used first."]]],
  ["Goal model", "Poisson model safeguards. See docs/MODEL.md.", [
    ["recency_half_life", "Matches until a result's weight halves. Lower = recent form counts more."],
    ["prior_weight", "Pseudo-matches of league-average shrinkage. Higher = more cautious with small samples and promoted teams."],
    ["min_matches_model", "Below this many matches per team the model returns “Insufficient data”."],
    ["min_matches_stat", "Below this, a statistic is flagged as a small sample; corners/cards models need it."],
    ["goal_cap", "Goals per team per match counted when estimating ratings (limits extreme results)."],
    ["min_league_matches", "Competition matches needed for its own baseline; otherwise a pooled baseline is used and flagged."],
    ["cross_league_shrink", "Share of rating deviation kept when teams come from different leagues (UEFA, cups)."],
  ]],
  ["Selection & rejection", "Gates every selection must pass. See docs/SCORING.md.", [
    ["min_leg_probability", "Minimum model probability (0–1) for a ticket leg."],
    ["min_leg_odds", "Minimum price for a leg; shorter prices add almost nothing to a ticket but carry full risk."],
    ["max_snapshot_candidate_odds", "Dataset snapshot lines priced above this are not considered as candidates."],
    ["min_evidence_score", "Minimum evidence score (0–85) for a market to be recommended."],
    ["min_selection_score", "Score for “acceptable” tier."],
    ["strong_selection_score", "Score for “strong” tier."],
    ["conflict_threshold", "Model vs historical hit-rate gap counted as conflicting evidence."],
    ["close_match_xg_gap", "Expected-goals gap below which teams count as closely matched (result markets excluded)."],
    ["max_dataset_age_days", "Dataset older than this rejects matches as outdated."],
    ["team_stale_days", "Team data older than this before kickoff is flagged."],
  ]],
  ["Accumulator", "", [["default_target_odds", "Default target."], ["max_legs", "Maximum legs the builder will use."], ["allow_snapshot_odds", "Allow labelled dataset snapshot prices in analysis and auto-build. Manual prices always win."]]],
  ["Optional local AI (Ollama)", "Runs on your computer. Disabled by default; the app works fully without it.", [
    ["ai_enabled", "Use a local Ollama model to write explanations (validated against the data)."],
    ["ollama_url", "Local Ollama address."],
    ["ollama_model", "Model name, e.g. llama3.1:8b, qwen2.5:7b, mistral."],
    ["allow_non_local_ai_host", "Allow a non-loopback Ollama host (e.g. another machine you own). Leave off unless you know you need it."],
    ["ai_timeout_seconds", "Timeout for one AI request."],
  ]],
];

export default function Settings() {
  const { data, loading, reload } = useFetch<G>("/api/settings");
  const ai = useFetch<G>("/api/ai/status");
  const { reloadStatus } = useStatus();
  const [vals, setVals] = useState<G>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (data) setVals(data.values); }, [data]);
  if (loading || !data) return <div className="page"><Loading /></div>;
  const save = async () => {
    setErr(null); setMsg(null);
    try { await api("/api/settings", { method: "PUT", json: vals }); setMsg("Saved. Analyses are recomputed with the new settings."); reload(); reloadStatus(); ai.reload(); }
    catch (e) { setErr((e as Error).message); }
  };
  const input = (k: string) => {
    const def = data.defaults[k];
    const v = vals[k];
    if (typeof def === "boolean") return <input type="checkbox" checked={!!v} onChange={(e) => setVals({ ...vals, [k]: e.target.checked })} />;
    if (typeof def === "number") return <input type="number" step="any" value={v ?? ""} onChange={(e) => setVals({ ...vals, [k]: e.target.value === "" ? "" : Number(e.target.value) })} style={{ width: 110 }} />;
    return <input value={v ?? ""} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} style={{ width: 240 }} />;
  };
  return (
    <div className="page">
      <div className="page-head"><div><h1>Settings</h1><p>Stored locally in SQLite. Changing a setting re-runs the deterministic engine — no cloud service is involved.</p></div>
        <div className="row"><button onClick={() => setVals(data.defaults)}>Restore defaults</button><button className="primary" onClick={save}>Save settings</button></div></div>
      {msg && <div className="notice good" style={{ marginBottom: 8 }}>{msg}</div>}
      <ErrorBox error={err} />
      <div className="stack">
        {GROUPS.map(([title, sub, items]) => (
          <Panel key={title} title={title} sub={sub} tight>
            <table className="tbl"><tbody>{items.map(([k, help]) => (
              <tr key={k}><td style={{ width: 260 }}><div className="mono">{k}</div><div className="tiny muted">default {String(data.defaults[k])}</div></td><td>{input(k)}</td><td className="small muted">{help}</td></tr>
            ))}</tbody></table>
            {title.startsWith("Optional local AI") && (
              <div className="panel-b">
                {ai.loading ? <Loading label="Checking for a local Ollama…" /> : ai.data && (
                  <div className="row small">
                    <Chip tone={ai.data.reachable ? "good" : "warn"}>{ai.data.reachable ? "Ollama reachable" : "Ollama not reachable"}</Chip>
                    {ai.data.reachable && <Chip tone={ai.data.model_installed ? "good" : "warn"}>{ai.data.model_installed ? `model ${ai.data.model} installed` : `model ${ai.data.model} not installed`}</Chip>}
                    {ai.data.models?.length > 0 && <span className="muted">available: {ai.data.models.join(", ")}</span>}
                    {ai.data.error && <span className="muted">{ai.data.error}</span>}
                    <button className="sm" onClick={ai.reload}>Re-check</button>
                  </div>
                )}
                <p className="small muted" style={{ marginTop: 6 }}>Install from <a href="https://ollama.com/" target="_blank" rel="noreferrer">ollama.com</a>, then run <span className="mono">ollama pull {vals.ollama_model}</span>. If Ollama is unavailable, slow, or writes a number that is not in the data, MatchEdge falls back to its deterministic explanation.</p>
              </div>
            )}
          </Panel>
        ))}
      </div>
    </div>
  );
}
