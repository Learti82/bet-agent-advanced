import { useEffect, useState } from "react";
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

function signedPct(x: number | null | undefined, d = 1) {
  if (x == null) return "—";
  return `${x > 0 ? "+" : ""}${(100 * x).toFixed(d)}%`;
}

function ClvPanel({ clv }: { clv: G }) {
  const o = clv.overall;
  return (
    <Panel title="Closing-line value" sub="did you beat Bet365's final price?">
      {o.n === 0 ? <p className="small muted">No settled bets with a closing price yet. Save tickets and import after kickoff: closing prices come from football-data.co.uk (true Bet365 close for 1X2, Over/Under 2.5, main Asian line) or the last daily snapshot (approximate).</p> : (
        <>
          <div className="grid g3" style={{ marginBottom: 8 }}>
            <div><div className="muted small">Average CLV</div><div className="big-odds" style={{ fontSize: 22, color: o.avg_clv > 0 ? "var(--good)" : "var(--bad)" }}>{signedPct(o.avg_clv)}</div></div>
            <div><div className="muted small">Beat the close</div><div className="big-odds" style={{ fontSize: 22 }}>{pct(o.beat_close_share)}</div></div>
            <div><div className="muted small">Bets with a closing price</div><div className="big-odds" style={{ fontSize: 22 }}>{o.n}</div><div className="tiny muted">{pct(o.true_closing_share)} true Bet365 close</div></div>
          </div>
          <table className="tbl"><thead><tr><th>Market type</th><th className="num">n</th><th className="num">Avg CLV</th><th className="num">Beat close</th></tr></thead>
            <tbody>{Object.entries(clv.by_family).filter(([, v]: [string, any]) => v.n).map(([k, v]: [string, any]) => <tr key={k}><td>{k}</td><td className="num">{v.n}</td><td className="num">{signedPct(v.avg_clv)}</td><td className="num">{pct(v.beat_close_share)}</td></tr>)}</tbody></table>
        </>
      )}
      <p className="tiny muted" style={{ marginTop: 6 }}>{clv.note}</p>
    </Panel>
  );
}

function Backtest() {
  const [run, setRun] = useState<G | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = async () => { try { setRun(await api<G>("/api/backtest")); } catch (e) { setErr((e as Error).message); } };
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    if (run?.status !== "running") return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [run?.status]);
  const [engine, setEngine] = useState<"ml" | "statistical">("ml");
  const start = async () => {
    setErr(null);
    try { await api("/api/backtest", { method: "POST", json: { engine } }); await load(); } catch (e) { setErr((e as Error).message); }
  };
  const r = run?.result;
  const legsAll = r?.legs?.find((x: G) => x.season === "all");
  return (
    <Panel title="Profit backtest — weekend plan" sub={`past seasons, real Bet365 prices${r ? ` · ${r.engine === "ml" ? "trained ML model" : "statistical engine"}` : ""}`} actions={<>
      <div className="seg"><button className={engine === "ml" ? "on" : ""} onClick={() => setEngine("ml")}>ML model</button><button className={engine === "statistical" ? "on" : ""} onClick={() => setEngine("statistical")}>Statistical</button></div>
      <button className="primary" onClick={start} disabled={run?.status === "running"}>{run?.status === "running" ? "Running…" : r ? "Run again" : "Run backtest"}</button></>}>
      <ErrorBox error={err ?? (run?.status === "failed" ? run.error : null)} />
      {run?.status === "running" && <Loading label={`Replaying every weekend: ${run.progress}`} />}
      {engine === "ml" && <p className="tiny muted" style={{ marginBottom: 6 }}>ML mode uses only out-of-sample predictions saved during training (seasons the model never saw), so only the test seasons from the Model lab are replayed. Train the model first.</p>}
      {!r && run?.status !== "running" && <p className="small muted">Replays the weekend plan for every Saturday/Sunday of past seasons (football-data.co.uk), using only data available before each match and Bet365's pre-match prices of the time. Takes about a minute.</p>}
      {r && (
        <>
          {legsAll && (
            <div className={`notice ${legsAll.singles_roi > 0 && legsAll.avg_clv > 0 ? "good" : "warn"}`} style={{ marginBottom: 10 }}>
              <b>Selected legs ({legsAll.legs}):</b> won <b>{pct(legsAll.win_rate)}</b> — the model expected {pct(legsAll.model_avg)}, Bet365's prices implied {pct(legsAll.implied_avg)}.
              As singles: {signedPct(legsAll.singles_roi)} per bet. Against Bet365's closing price: average CLV {signedPct(legsAll.avg_clv)}, beat the close {pct(legsAll.beat_close_share)} of the time.
              {legsAll.win_rate < legsAll.implied_avg ? " The picks did not beat the bookmaker's own estimate: on these markets the model shows no edge." : legsAll.avg_clv > 0 ? " Positive CLV is encouraging, but check it holds season by season." : ""}
            </div>
          )}
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Season</th><th className="num">Target</th><th className="num">Tickets</th><th className="num">Won</th><th className="num">Model expected</th><th className="num">Avg odds</th><th className="num">Avg legs</th><th className="num">Profit (u)</th><th className="num">ROI</th><th className="num">Worst losing run</th><th className="num">Max drawdown</th></tr></thead>
            <tbody>{r.tickets.filter((x: G) => x.subset === "all tickets" && x.tickets).map((x: G) => (
              <tr key={x.season + x.target} style={x.season === "all" ? { fontWeight: 650 } : undefined}>
                <td>{x.season === "all" ? "All seasons" : `20${x.season.slice(0, 2)}/${x.season.slice(2)}`}</td><td className="num">{x.target}</td><td className="num">{x.tickets}</td><td className="num">{x.won}</td><td className="num">{x.model_expected_wins}</td><td className="num">{num(x.avg_odds)}</td><td className="num">{x.avg_legs}</td>
                <td className="num" style={{ color: x.profit_units > 0 ? "var(--good)" : "var(--bad)" }}>{num(x.profit_units)}</td><td className="num">{signedPct(x.roi)}</td><td className="num">{x.longest_losing_run}</td><td className="num">{num(x.max_drawdown_units)}</td>
              </tr>
            ))}</tbody>
          </table></div>
          <div className="grid g2" style={{ marginTop: 10 }}>
            <table className="tbl"><thead><tr><th>Legs by season</th><th className="num">n</th><th className="num">Won</th><th className="num">Model</th><th className="num">Implied</th><th className="num">CLV</th></tr></thead>
              <tbody>{r.legs.filter((x: G) => x.legs).map((x: G) => <tr key={x.season}><td>{x.season === "all" ? "All" : x.season}</td><td className="num">{x.legs}</td><td className="num">{pct(x.win_rate)}</td><td className="num">{pct(x.model_avg)}</td><td className="num">{pct(x.implied_avg)}</td><td className="num">{signedPct(x.avg_clv)}</td></tr>)}</tbody></table>
            <table className="tbl"><thead><tr><th>Legs by market</th><th className="num">n</th><th className="num">Won</th><th className="num">Implied</th><th className="num">Singles ROI</th><th className="num">CLV</th></tr></thead>
              <tbody>{Object.entries(r.legs_by_market).map(([k, x]: [string, any]) => <tr key={k}><td>{k}</td><td className="num">{x.legs}</td><td className="num">{pct(x.win_rate)}</td><td className="num">{pct(x.implied_avg)}</td><td className="num">{signedPct(x.singles_roi)}</td><td className="num">{signedPct(x.avg_clv)}</td></tr>)}</tbody></table>
          </div>
          <p className="tiny muted" style={{ marginTop: 8 }}>
            Ran {run.finished_at?.replace("T", " ").slice(0, 16)} UTC on {r.weekends} weekends, leagues: {r.competitions.join(", ")}. Limits: only markets with historical Bet365 prices (1X2, Over/Under 2.5, the main Asian handicap line) — the live app also uses BTTS, other goal lines, double chance, corners and cards, which cannot be tested here; UEFA midweek slots are not in the historical files. 1 unit staked per ticket. Past results do not guarantee future ones.
          </p>
        </>
      )}
    </Panel>
  );
}

function LeagueStrength() {
  const { data } = useFetch<G>("/api/league-strength");
  if (!data || !data.leagues?.length) return null;
  return (
    <Panel title="League strength" sub={`learned from ${data.n_matches} European matches this season`} tight>
      <div className="panel-b">
        <p className="small muted">{data.note} {data.validation}</p>
        <div className="tbl-wrap" style={{ maxHeight: 360 }}><table className="tbl">
          <thead><tr><th>League</th><th className="num">Strength</th><th className="num">± (1 sd)</th><th className="num">Goal factor</th><th className="num">Matches</th></tr></thead>
          <tbody>{data.leagues.map((l: G) => <tr key={l.league}><td>{l.name}</td><td className="num">{l.strength > 0 ? "+" : ""}{l.strength.toFixed(2)}</td><td className="num muted">{l.sd.toFixed(2)}</td><td className="num">{l.goal_factor}</td><td className="num">{l.matches}</td></tr>)}</tbody>
        </table></div>
      </div>
    </Panel>
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
          <div style={{ marginBottom: 12 }}><ClvPanel clv={p.clv} /></div>
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
      <Backtest />
      <div style={{ height: 12 }} />
      <ModelCheck />
      <div style={{ height: 12 }} />
      <LeagueStrength />
      <div style={{ height: 12 }} />
      <Panel title="Predictions" sub="settle manually when the dataset lacks the statistic" tight>
        {preds.loading ? <Loading /> : (preds.data ?? []).length === 0 ? <Empty>No predictions yet.</Empty> : (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Date</th><th>Match</th><th>Market</th><th className="num">Odds</th><th className="num">Close</th><th className="num">CLV</th><th className="num">Model</th><th className="num">DQ</th><th>Status</th><th>Result</th><th>Manual</th></tr></thead>
            <tbody>{(preds.data ?? []).map((r) => (
              <tr key={r.id}>
                <td className="num small nowrap">{(r.kickoff_utc ?? r.created_at).slice(0, 10)}</td>
                <td><Link to={`/match/${enc(r.match_id)}`}>{r.match_label}</Link><div className="muted tiny">{r.competition}</div></td>
                <td>{r.market} {r.selection} {r.line ?? ""}</td>
                <td className="num">{fmtOdds(r.odds)}<div className="muted tiny">{r.odds_source}</div></td>
                <td className="num" title={r.closing_source ?? ""}>{fmtOdds(r.closing_odds)}{r.closing_source && !r.closing_source.startsWith("Bet365 closing") && <div className="tiny muted">approx.</div>}</td>
                <td className="num" style={{ color: r.clv == null ? undefined : r.clv > 0 ? "var(--good)" : "var(--bad)" }}>{signedPct(r.clv)}</td>
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
