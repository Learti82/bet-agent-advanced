import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Chip, ErrorBox, Loading, Panel } from "../components/ui";
import { num, pct } from "../format";

/* eslint-disable @typescript-eslint/no-explicit-any */
type G = Record<string, any>;

const NAMES: Record<string, string> = {
  engine: "Statistical engine (current)", ml_stats: "ML — statistics only", ml_market: "ML — statistics + Bet365 odds", bet365: "Bet365's own odds",
};
const TARGET_NAMES: Record<string, string> = { y_1x2: "Match result (1X2)", y_o25: "Over 2.5 goals", y_btts: "Both teams to score" };
const FEATURE_NAMES: Record<string, string> = {
  eng_h: "engine P(home win)", eng_d: "engine P(draw)", eng_a: "engine P(away win)", eng_o25: "engine P(over 2.5)", eng_btts: "engine P(BTTS)",
  eng_lh: "engine expected home goals", eng_la: "engine expected away goals", elo_diff: "Elo difference (incl. home advantage)",
  elo_exp_h: "Elo expected score", elo_h: "home Elo", elo_a: "away Elo", sf_h: "home shots for", sa_h: "home shots against",
  sf_a: "away shots for", sa_a: "away shots against", stf_h: "home shots on target for", sta_h: "home shots on target against",
  stf_a: "away shots on target for", sta_a: "away shots on target against", cf_h: "home corners for", ca_h: "home corners against",
  cf_a: "away corners for", ca_a: "away corners against", sot_share_h: "home share of shots on target", sot_share_a: "away share of shots on target",
  ppg_h: "home points per game (season)", ppg_a: "away points per game (season)", form_h: "home recent form", form_a: "away recent form",
  att_h: "home attack vs league", att_a: "away attack vs league", def_h: "home defence vs league", def_a: "away defence vs league",
  gf_h: "home goals for", ga_h: "home goals against", gf_a: "away goals for", ga_a: "away goals against",
  exp_h: "expected home goals (form)", exp_a: "expected away goals (form)", rest_h: "home rest days", rest_a: "away rest days",
};

function Comparison({ pooled }: { pooled: G }) {
  return (
    <div className="tbl-wrap"><table className="tbl">
      <thead><tr><th>Market</th><th>Predictor</th><th className="num">Log loss</th><th className="num">Brier</th><th className="num">Accuracy</th><th className="num">Matches</th></tr></thead>
      <tbody>{Object.entries(pooled).map(([t, by]: [string, any]) => {
        const best = Math.min(...Object.values(by).map((x: any) => x.log_loss));
        return Object.entries(by).map(([name, x]: [string, any], i) => (
          <tr key={t + name} style={x.log_loss === best ? { background: "var(--accent-soft)" } : undefined}>
            <td>{i === 0 ? <b>{TARGET_NAMES[t]}</b> : ""}</td><td>{NAMES[name] ?? name}{x.log_loss === best && <> <Chip tone="good">best</Chip></>}</td>
            <td className="num">{x.log_loss.toFixed(4)}</td><td className="num">{x.brier.toFixed(4)}</td><td className="num">{pct(x.accuracy, 1)}</td><td className="num">{x.n}</td>
          </tr>
        ));
      })}</tbody>
    </table></div>
  );
}

function Calibration({ bins }: { bins: G[] }) {
  const data = bins.map((b) => ({ bin: b.bin, Predicted: 100 * b.predicted, Actual: 100 * b.actual, n: b.n }));
  return (
    <ResponsiveContainer width="100%" height={230}>
      <ComposedChart data={data} margin={{ top: 6, right: 10, left: -18, bottom: 0 }}>
        <CartesianGrid strokeDasharray="2 3" stroke="var(--line)" />
        <XAxis dataKey="bin" tick={{ fontSize: 11, fill: "var(--muted)" }} />
        <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 11, fill: "var(--muted)" }} />
        <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", fontSize: 12 }} formatter={(v: number, k: string, it: G) => `${v.toFixed(1)}%${k === "Actual" ? ` (n=${it.payload.n})` : ""}`} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Line dataKey="Predicted" stroke="var(--muted)" strokeDasharray="4 3" dot={false} />
        <Scatter dataKey="Actual" fill="var(--accent)" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export default function ModelLab() {
  const [st, setSt] = useState<G | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [season, setSeason] = useState<string | null>(null);
  const load = async () => { try { setSt(await api<G>("/api/ml")); } catch (e) { setErr((e as Error).message); } };
  useEffect(() => { void load(); }, []);
  const running = st?.run?.status === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [running]);
  const train = async () => { setErr(null); try { await api("/api/ml/train", { method: "POST" }); await load(); } catch (e) { setErr((e as Error).message); } };
  const setEngine = async (v: string) => { await api("/api/settings", { method: "PUT", json: { prediction_engine: v } }); await load(); };
  const r = st?.run?.result;
  const seasons = r ? Object.keys(r.seasons) : [];
  const sel = season ?? seasons[seasons.length - 1];
  const meta = st?.model_meta;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Model lab</h1>
          <p>Train a machine-learning model on every past season on this computer and test it honestly: it is trained only on seasons <i>before</i> each test season and scored on matches it has never seen, against the current statistical engine and Bet365's own odds. Better predictions do not automatically mean profit — the betting simulation below shows that separately.</p>
        </div>
        <button className="primary" onClick={train} disabled={running}>{running ? "Training…" : meta ? "Retrain model" : "Train model"}</button>
      </div>
      <ErrorBox error={err ?? (st?.run?.status === "failed" ? st.run.error : null) ?? st?.load_error ?? null} />
      {running && <Loading label={`Training (about 1–2 minutes): ${st?.run?.progress}`} />}

      <div className="grid g3" style={{ marginBottom: 12 }}>
        <div className="panel stat"><div className="k">Trained model</div><div className="v" style={{ fontSize: 17 }}>{meta ? meta.trained_at.replace("T", " ").slice(0, 16) + " UTC" : "none yet"}</div><div className="d">{meta ? `${meta.rows.toLocaleString()} matches · seasons ${meta.seasons.join(", ")}` : "Needs the historical seasons (Data sources → import)."}</div></div>
        <div className="panel stat"><div className="k">Used in analysis</div>
          <div className="row" style={{ marginTop: 6 }}>
            <div className="seg">{[["auto", "ML where validated"], ["statistical", "Statistical only"]].map(([v, l]) => <button key={v} className={(st?.prediction_engine ?? "auto") === v ? "on" : ""} onClick={() => setEngine(v)}>{l}</button>)}</div>
          </div>
          <div className="d" style={{ marginTop: 6 }}>ML is applied to domestic-league fixtures in the 22 covered divisions, per market only where it beat the statistical engine out of sample. UEFA and cup fixtures keep the statistical engine.</div>
        </div>
        <div className="panel stat"><div className="k">How it works</div><div className="d" style={{ marginTop: 4 }}>Gradient-boosted trees (scikit-learn) on walk-forward features: Elo, form, goals, shots, shots on target, corners, rest, league scoring level and the statistical engine's own probabilities; a second variant also sees Bet365's pre-match prices. See docs/ML.md.</div></div>
      </div>

      {r && (
        <div className="stack">
          <Panel title="Accuracy on unseen seasons" sub={`pooled over ${seasons.join(", ")} — lower log loss / Brier is better`}>
            <Comparison pooled={r.pooled} />
            <p className="small muted" style={{ marginTop: 8 }}>Accuracy for match result = how often the most likely outcome happened. Even the bookmaker gets this right only about half the time — football has a lot of randomness. The useful improvement is in log loss/Brier: probabilities that are closer to reality.</p>
          </Panel>

          <div className="row">{seasons.map((s) => <button key={s} className={`sm ${s === sel ? "primary" : ""}`} onClick={() => setSeason(s)}>Test season 20{s.slice(0, 2)}/{s.slice(2)}</button>)}</div>
          {sel && r.seasons[sel] && (
            <div className="grid g2">
              <Panel title="Calibration — home win" sub={`ML with odds, 20${sel.slice(0, 2)}/${sel.slice(2)} (trained on ${r.seasons[sel].train_rows.toLocaleString()} earlier matches)`}>
                <Calibration bins={r.seasons[sel].targets.y_1x2.calibration_ml_market} />
                <p className="tiny muted">Dots on the dashed line = the probability means what it says.</p>
              </Panel>
              <Panel title="Calibration — Over 2.5" sub="ML with odds">
                <Calibration bins={r.seasons[sel].targets.y_o25.calibration_ml_market} />
              </Panel>
            </div>
          )}

          <Panel title="Value-betting simulation" sub="1 unit on every 1X2 / Over-Under 2.5 price where model probability × Bet365 pre-match odds − 1 exceeds the edge threshold">
            <div className="tbl-wrap"><table className="tbl">
              <thead><tr><th>Season</th><th>Predictor</th><th className="num">Edge ≥</th><th className="num">Bets</th><th className="num">Won</th><th className="num">Profit (u)</th><th className="num">ROI</th><th className="num">CLV</th><th className="num">Beat close</th></tr></thead>
              <tbody>{seasons.flatMap((s) => Object.entries(r.seasons[s].betting).flatMap(([name, rows]: [string, any]) => rows.map((x: G) => (
                <tr key={s + name + x.edge_threshold}>
                  <td>20{s.slice(0, 2)}/{s.slice(2)}</td><td>{NAMES[name]}</td><td className="num">{pct(x.edge_threshold)}</td><td className="num">{x.bets}</td><td className="num">{pct(x.win_rate)}</td>
                  <td className="num" style={{ color: x.profit_units > 0 ? "var(--good)" : "var(--bad)" }}>{num(x.profit_units, 1)}</td><td className="num">{pct(x.roi, 1)}</td><td className="num">{pct(x.avg_clv, 1)}</td><td className="num">{pct(x.beat_close)}</td>
                </tr>
              ))))}</tbody>
            </table></div>
            <p className="small muted" style={{ marginTop: 8 }}>Every row is out of sample. If these are negative, the model does not find prices Bet365 got wrong — use it to rank the most likely selections, not as a money machine. To compare the weekend plan built with the ML model against the statistical engine, run the <Link to="/performance">profit backtest</Link> with "ML".</p>
          </Panel>

          <Panel title="What the model relies on" sub="permutation importance, match result, statistics-only model">
            <table className="tbl"><tbody>{r.feature_importance.map((f: G) => {
              const max = r.feature_importance[0].importance || 1;
              return (
                <tr key={f.feature}><td style={{ width: 300 }}>{FEATURE_NAMES[f.feature] ?? f.feature}</td>
                  <td><div className="bar-cell"><div className="b" style={{ width: `${Math.max(2, (100 * f.importance) / max)}%` }} /><span className="tiny muted">{f.importance.toFixed(4)}</span></div></td></tr>
              );
            })}</tbody></table>
            <p className="tiny muted" style={{ marginTop: 6 }}>How much the log loss gets worse when a feature is shuffled. The statistical engine's own probabilities matter most — the trees learn to correct them using Elo, shots and corners.</p>
          </Panel>
          <p className="tiny muted">Trained {meta?.trained_at} in {meta?.seconds}s with scikit-learn {meta?.sklearn}. Model file: {st?.model_file}. Retrain after each import to include the newest matches.</p>
        </div>
      )}
      {!r && !running && st && <div className="panel"><div className="empty">No training run yet. Make sure the historical seasons are imported (Data sources), then press <b>Train model</b>.</div></div>}
    </div>
  );
}
