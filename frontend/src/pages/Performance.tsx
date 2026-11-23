import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ErrorBar, Legend, Line, ComposedChart, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { api, enc } from "../api";
import { Empty, ErrorBox, Loading, Panel, Stat, StatusChip, useFetch } from "../components/ui";
import { fmtOdds, num, pct } from "../format";

/* eslint-disable @typescript-eslint/no-explicit-any */
type G = Record<string, any>;

function GroupRow({ name, g }: { name: string; g: G }) {
  return (
    <tr>
      <td>{name}</td><td className="num">{g.total}</td><td className="num">{g.settled}</td><td className="num">{g.won}</td><td className="num">{g.lost}</td><td className="num">{g.void}</td>
      <td className="num">{pct(g.hit_rate)}</td><td className="num">{pct(g.avg_model_probability)}</td><td className="num">{num(g.avg_odds)}</td>
      <td className="num" style={{ color: g.flat_stake_profit_units > 0 ? "var(--good)" : g.flat_stake_profit_units < 0 ? "var(--bad)" : undefined }}>{num(g.flat_stake_profit_units)}</td>
      <td className="num">{g.brier_score ?? "—"}</td>
    </tr>
  );
}

function ModelCheck() {
  const { data, loading, error } = useFetch<G>("/api/model-check");
  return (
    <Panel title="Model check" sub="walk-forward on this season's finished league matches" tight>
      <div className="panel-b">
        <ErrorBox error={error} />
        {loading ? <Loading label="Re-predicting every finished match from earlier data only…" /> : data && (
          <>
            <p className="small">{data.matches} matches. Each prediction was made with only the matches played before it, then compared with the result.
              {data.high_confidence && <> When the model said <b>80% or more</b>, the average prediction was <b>{pct(data.high_confidence.predicted)}</b> and it actually happened <b>{pct(data.high_confidence.actual)}</b> of the time (n={data.high_confidence.n}).</>}
            </p>
            <div className="tbl-wrap"><table className="tbl">
              <thead><tr><th>Market</th>{["50–60%", "60–70%", "70–80%", "80–90%", "90–100%"].map((b) => <th key={b} className="num">{b}</th>)}</tr></thead>
              <tbody>{data.markets.map((m: G) => (
                <tr key={m.market}><td>{m.market}</td>{["50–60%", "60–70%", "70–80%", "80–90%", "90–100%"].map((b) => {
                  const x = m.bins.find((y: G) => y.range === b);
                  if (!x) return <td key={b} className="num muted">—</td>;
                  const gap = Math.round(100 * (x.predicted - x.actual));
                  return <td key={b} className="num" title={`n=${x.n}, 95% band ${pct(x.actual_low)}–${pct(x.actual_high)}`}>{pct(x.actual)} <span className="tiny" style={{ color: Math.abs(gap) <= 2 ? "var(--muted)" : gap > 0 ? "var(--bad)" : "var(--good)" }}>({gap > 0 ? "−" : "+"}{Math.abs(gap)})</span>{x.n < 100 && <div className="tiny muted">n={x.n}, small</div>}</td>;
                })}</tr>
              ))}</tbody>
            </table></div>
            <p className="tiny muted" style={{ marginTop: 6 }}>Cells show how often the outcome happened for predictions in that band; the bracket is actual minus predicted in points (red = the model was overconfident). Settings: prior {data.settings.prior_weight}, half-life {data.settings.recency_half_life}. {data.note}</p>
          </>
        )}
      </div>
    </Panel>
  );
}

export default function Performance() {
  const perf = useFetch<G>("/api/performance");
  const preds = useFetch<G[]>("/api/predictions");
  const [msg, setMsg] = useState<string | null>(null);
  const settleAuto = async () => { const r = await api<G>("/api/predictions/settle-auto", { method: "POST" }); setMsg(`Checked ${r.checked}, settled ${r.settled}, ${r.needs_manual} need manual settlement.`); perf.reload(); preds.reload(); };
  const settle = async (id: number, status: string) => { await api(`/api/predictions/${id}/settle`, { method: "POST", json: { status } }); perf.reload(); preds.reload(); };
  const delTicket = async (id: number) => { await api(`/api/tickets/${id}`, { method: "DELETE" }); perf.reload(); preds.reload(); };
  if (perf.loading && !perf.data) return <div className="page"><Loading /></div>;
  const p = perf.data;
  const cal = (p?.calibration ?? []).map((c: G) => ({ ...c, predictedPct: 100 * c.predicted, actualPct: 100 * c.actual, err: [100 * (c.actual - c.actual_low), 100 * (c.actual_high - c.actual)] }));
  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Historical performance</h1><p>Every saved ticket stores its selections with the price, model estimate and data quality at prediction time. Imports settle them automatically from real results; markets whose statistic is missing must be settled by you.</p></div>
        <button onClick={settleAuto}>Settle from imported results</button>
      </div>
      {msg && <div className="notice good small" style={{ marginBottom: 8 }}>{msg}</div>}
      <ErrorBox error={perf.error} />
      {p && (
        <>
          <div className="notice warn" style={{ marginBottom: 12 }}>{p.sample_note} {p.disclaimer}</div>
          <div className="grid g4" style={{ marginBottom: 12 }}>
            <Stat k="Selections tracked" v={p.overall.total} d={`${p.overall.settled} settled · ${p.overall.pending} pending`} />
            <Stat k="Hit rate" v={pct(p.overall.hit_rate)} d={`model average ${pct(p.overall.avg_model_probability)}`} />
            <Stat k="Flat-stake profit (singles view)" v={`${num(p.overall.flat_stake_profit_units)} u`} d={`ROI ${pct(p.overall.roi, 1)} · avg odds ${num(p.overall.avg_odds)}`} />
            <Stat k="Brier score" v={p.overall.brier_score ?? "—"} d="lower is better; 0.25 = coin-flip guessing" />
          </div>
          <div className="grid g2" style={{ marginBottom: 12 }}>
            <Panel title="Estimated probability calibration" sub="predicted vs actual, with 95% bands">
              {cal.length === 0 ? <Empty>No settled selections yet.</Empty> : (
                <ResponsiveContainer width="100%" height={240}>
                  <ComposedChart data={cal} margin={{ top: 6, right: 10, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="2 3" stroke="var(--line)" />
                    <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: "var(--muted)" }} />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "var(--muted)" }} unit="%" />
                    <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", fontSize: 12 }} formatter={(v: number) => `${v.toFixed(0)}%`} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line dataKey="predictedPct" name="Model estimate" stroke="var(--muted)" strokeDasharray="4 3" dot={false} />
                    <Scatter dataKey="actualPct" name="Actual hit rate" fill="var(--accent)"><ErrorBar dataKey="err" width={4} stroke="var(--accent)" /></Scatter>
                  </ComposedChart>
                </ResponsiveContainer>
              )}
              <div className="small muted">{cal.map((c: G) => `${c.bucket}: n=${c.n}`).join(" · ")}</div>
            </Panel>
            <Panel title="Performance by odds range">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={p.by_odds.map((b: G) => ({ range: b.range, "Hit rate": b.hit_rate == null ? 0 : 100 * b.hit_rate, n: b.settled }))} margin={{ top: 6, right: 10, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="2 3" stroke="var(--line)" vertical={false} />
                  <XAxis dataKey="range" tick={{ fontSize: 11, fill: "var(--muted)" }} />
                  <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 11, fill: "var(--muted)" }} />
                  <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", fontSize: 12 }} formatter={(v: number, k: string, it: G) => (k === "Hit rate" ? `${v.toFixed(0)}% (n=${it.payload.n})` : v)} />
                  <Bar dataKey="Hit rate" fill="var(--accent)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>
          <Panel title="By market type and odds" tight>
            <div className="tbl-wrap"><table className="tbl">
              <thead><tr><th>Group</th><th className="num">Total</th><th className="num">Settled</th><th className="num">Won</th><th className="num">Lost</th><th className="num">Void</th><th className="num">Hit rate</th><th className="num">Model avg</th><th className="num">Avg odds</th><th className="num">Profit (u)</th><th className="num">Brier</th></tr></thead>
              <tbody>
                <GroupRow name="Overall" g={p.overall} />
                <GroupRow name="Goals markets" g={p.by_family.goals} />
                <GroupRow name="Corners markets" g={p.by_family.corners} />
                <GroupRow name="Cards markets" g={p.by_family.cards} />
                <GroupRow name="Match winner / result" g={p.by_family.result} />
                <GroupRow name="Asian handicap" g={p.by_family.handicap} />
                {p.by_odds.map((b: G) => <GroupRow key={b.range} name={`Odds ${b.range}`} g={b} />)}
              </tbody>
            </table></div>
          </Panel>
          <div style={{ height: 12 }} />
          <Panel title="Saved tickets" tight>
            {p.tickets.length === 0 ? <Empty>No saved tickets. Save one from the accumulator builder.</Empty> : (
              <table className="tbl"><thead><tr><th>#</th><th>Created</th><th>Name</th><th className="num">Target</th><th className="num">Odds</th><th className="num">Legs</th><th>Status</th><th></th></tr></thead>
                <tbody>{p.tickets.map((t: G) => <tr key={t.id}><td>{t.id}</td><td className="num small">{t.created_at.replace("T", " ").slice(0, 16)}</td><td>{t.name ?? "—"}</td><td className="num">{t.target_odds ?? "—"}</td><td className="num"><b>{fmtOdds(t.combined_odds)}</b></td><td className="num">{t.n_selections}</td><td><StatusChip value={t.status} /></td><td><button className="sm ghost danger" onClick={() => delTicket(t.id)}>Delete</button></td></tr>)}</tbody></table>
            )}
          </Panel>
        </>
      )}
      <div style={{ height: 12 }} />
      <ModelCheck />
      <div style={{ height: 12 }} />
      <Panel title="Predictions" sub="settle manually when the dataset lacks the statistic" tight>
        {preds.loading ? <Loading /> : (preds.data ?? []).length === 0 ? <Empty>No predictions yet.</Empty> : (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Date</th><th>Match</th><th>Market</th><th className="num">Odds</th><th className="num">Model</th><th className="num">DQ</th><th>Status</th><th>Result</th><th>Manual</th></tr></thead>
            <tbody>{(preds.data ?? []).map((r) => (
              <tr key={r.id}>
                <td className="num small nowrap">{(r.kickoff_utc ?? r.created_at).slice(0, 10)}</td>
                <td><Link to={`/match/${enc(r.match_id)}`}>{r.match_label}</Link><div className="muted tiny">{r.competition}</div></td>
                <td>{r.market} {r.selection} {r.line ?? ""}</td>
                <td className="num">{fmtOdds(r.odds)}<div className="muted tiny">{r.odds_source}</div></td>
                <td className="num">{pct(r.model_probability)}</td>
                <td className="num">{r.data_quality != null ? Math.round(r.data_quality) : "—"}</td>
                <td><StatusChip value={r.status} /></td>
                <td className="small muted">{r.result_detail ?? ""}</td>
                <td className="nowrap">{["won", "lost", "void"].map((s) => <button key={s} className="sm ghost" onClick={() => settle(r.id, s)}>{s}</button>)}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Panel>
    </div>
  );
}
