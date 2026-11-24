import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, enc, qs, type Analysis, type Candidate, type Factor, type Fixture } from "../api";
import PasteOdds from "../components/PasteOdds";
import { Chip, Empty, ErrorBox, FormSeq, Loading, Panel, StatusChip, useFetch } from "../components/ui";
import { RISK_TONE, TIME_LABEL, addDays, fmtOdds, hr, nowLocalInput, pct, todayLocal } from "../format";
import { useTicket } from "../ticket";

const TABS = ["Markets", "Teams", "Corners & cards", "Odds", "Research", "Fixture", "Model"] as const;
type Tab = (typeof TABS)[number];

export default function MatchResearch() {
  const { id } = useParams();
  if (!id) return <MatchPicker />;
  return <MatchView id={decodeURIComponent(id)} />;
}

function MatchPicker() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const today = todayLocal();
  const { data, loading, error } = useFetch<Fixture[]>(`/api/fixtures${qs({ date_from: today, date_to: addDays(today, 3), include_ineligible: false })}`);
  const list = (data ?? []).filter((f) => !q || `${f.home} ${f.away} ${f.competition_name}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="page">
      <div className="page-head"><div><h1>Match research</h1><p>Pick a fixture (next four days) or open one from the fixtures list.</p></div></div>
      <Panel title="Find a match" actions={<input placeholder="Team or competition…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />} tight>
        <ErrorBox error={error} />
        {loading ? <Loading /> : list.length === 0 ? <Empty>No matching pre-match fixtures.</Empty> : (
          <div className="tbl-wrap" style={{ maxHeight: 600 }}>
            <table className="tbl"><tbody>
              {list.slice(0, 300).map((f) => (
                <tr key={f.id} className="click" onClick={() => nav(`/match/${enc(f.id)}`)}>
                  <td className="num nowrap">{f.kickoff_local ?? `${f.date} TBC`}</td>
                  <td>{f.competition_name}</td>
                  <td className="teams">{f.home}<span className="v">v</span>{f.away}</td>
                </tr>
              ))}
            </tbody></table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function MatchView({ id }: { id: string }) {
  const { data: a, error, loading, reload } = useFetch<Analysis>(`/api/matches/${enc(id)}/analysis`, [id]);
  const [tab, setTab] = useState<Tab>("Markets");
  const [ai, setAi] = useState<Analysis | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  useEffect(() => setAi(null), [id]);
  if (loading && !a) return <div className="page"><Loading label="Running the statistical engine…" /></div>;
  if (error) return <div className="page"><ErrorBox error={error} onRetry={reload} /></div>;
  if (!a) return null;
  const fx: Fixture = a.fixture;
  const status: string = a.decision.status;
  const askAi = async () => {
    setAiBusy(true);
    try { setAi(await api<Analysis>(`/api/matches/${enc(id)}/analysis?ai=true`)); } finally { setAiBusy(false); }
  };
  const explanation = (ai ?? a).explanation;

  return (
    <div className="page">
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="hero">
          <div>
            <div className="muted small">{fx.competition_name} · {fx.country}{fx.score ? ` · final ${fx.score}` : ""}</div>
            <div className="vs">{fx.home}<span>vs</span>{fx.away}</div>
            <div className="row" style={{ marginTop: 6 }}>
              <span className="num">{fx.kickoff_local ?? `${fx.date} (time unknown)`} {fx.timezone}</span>
              <Chip tone={["corroborated", "user_corrected"].includes(fx.time_certainty) ? "good" : fx.time_certainty === "single_source" ? "" : "warn"} title={fx.time_notes.join(" ")}>{TIME_LABEL[fx.time_certainty] ?? fx.time_certainty}</Chip>
              {fx.verified ? <Chip tone="good">verified fixture</Chip> : <Chip tone="outline">unverified (dataset only)</Chip>}
              <Chip tone={fx.prematch_eligible ? "info" : "muted"}>{fx.prematch_status}</Chip>
            </div>
          </div>
          <div className="row" style={{ alignItems: "flex-start" }}>
            <div className="stack" style={{ gap: 4, alignItems: "flex-end" }}>
              <StatusChip value={status} />
              <span className="muted tiny">analysis {a.generated_at.slice(11, 16)} UTC</span>
            </div>
          </div>
        </div>
      </div>

      <DecisionBanner status={status} factors={a.decision.factors} />

      <div className="grid g4" style={{ margin: "12px 0" }}>
        <ScoreCard k="Match research score" v={a.research_score.score} d="Clarity of the statistical picture — not a probability" />
        <ScoreCard k="Data quality" v={a.data_quality.score} d={`${a.data_quality.label} · sample, coverage, freshness, fixture certainty`} />
        <div className="panel stat">
          <div className="k">Risk assessment</div>
          <div className="v"><Chip tone={RISK_TONE[a.risk.level]}>{a.risk.level}</Chip></div>
          <div className="d">{a.risk.factors.filter((f: Factor) => f.severity !== "low").length} medium/high factors</div>
        </div>
        <div className="panel stat">
          <div className="k">Model expected goals</div>
          <div className="v num">{a.model.available ? `${a.model.expected_goals.home} – ${a.model.expected_goals.away}` : "—"}</div>
          <div className="d">{a.model.available ? `${a.prediction_engine === "ml" ? `Trained ML model (${a.ml_variant === "market" ? "stats + Bet365 odds" : "stats only"})` : "Statistical (Poisson)"} · total ${a.model.expected_goals.total} vs league ${a.league.avg_total_goals}` : a.model.reason}</div>
        </div>
      </div>

      <Panel title="Analyst view" sub={explanation.ai?.used ? `local model ${explanation.ai.model} · numbers verified` : "deterministic engine"}
        actions={<button onClick={askAi} disabled={aiBusy}>{aiBusy ? "Asking local AI…" : "Ask local AI (Ollama)"}</button>}>
        <Explanation e={explanation} />
      </Panel>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="tabs">{TABS.map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}{t === "Research" && a.evidence.length ? ` (${a.evidence.length})` : ""}</button>)}</div>
        <div className="panel-b">
          {tab === "Markets" && <Markets a={a} onOdds={() => setTab("Odds")} />}
          {tab === "Teams" && <Teams a={a} />}
          {tab === "Corners & cards" && <CornersCards a={a} />}
          {tab === "Odds" && <OddsTab a={a} onSaved={reload} />}
          {tab === "Research" && <ResearchTab a={a} onSaved={reload} />}
          {tab === "Fixture" && <FixtureTab a={a} onSaved={reload} />}
          {tab === "Model" && <ModelTab a={a} />}
        </div>
      </div>
    </div>
  );
}

function ScoreCard({ k, v, d }: { k: string; v: number; d: string }) {
  return (
    <div className="panel stat">
      <div className="k">{k}</div>
      <div className="v">{Math.round(v)}<span className="muted small"> / 100</span></div>
      <div className="d">{d}</div>
      <div className="meter"><i style={{ width: `${v}%` }} /></div>
    </div>
  );
}

function DecisionBanner({ status, factors }: { status: string; factors: Factor[] }) {
  const main = factors.filter((f) => f.action !== "info");
  const info = factors.filter((f) => f.action === "info");
  const tone = status === "candidate" ? "good" : status === "flagged" ? "warn" : status === "rejected" ? "bad" : "";
  const head = { candidate: "Candidate — passes the rejection rules", flagged: "Flagged — usable only with the risks below in mind", rejected: "Rejected — not a betting opportunity on this evidence", ineligible: "Not available for a pre-match ticket" }[status] ?? status;
  return (
    <div className={`notice ${tone}`}>
      <b>{head}</b>
      {main.length > 0 && <ul>{main.map((f, i) => <li key={i}><Chip tone={f.severity === "high" ? "bad" : f.severity === "medium" ? "warn" : ""}>{f.severity}</Chip> {f.message}</li>)}</ul>}
      {info.length > 0 && <details className="reasons" style={{ marginTop: 4 }}><summary>{info.length} informational notes</summary><ul>{info.map((f, i) => <li key={i}>{f.message}</li>)}</ul></details>}
    </div>
  );
}

function Explanation({ e }: { e: Analysis }) {
  const t = e.ai?.used ? e.ai.text : null;
  return (
    <div className="grid g2">
      <div>
        <div className="row" style={{ marginBottom: 6 }}>
          <span className="muted small">Selected market</span>
          <b>{e.selected_market ?? "None"}</b>
        </div>
        <p><b>{e.verdict}</b></p>
        {t ? (
          <>
            <p>{t.summary}</p>
            <p><b>Why this market:</b> {t.why_selected}</p>
            <p><b>Market comparison:</b> {t.market_comparison}</p>
            {t.contradictions?.length > 0 && <><b>Contradictions</b><ul className="plain explain">{t.contradictions.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></>}
          </>
        ) : (
          <ul className="plain explain">{e.reasoning.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
        )}
        {e.ai && !e.ai.used && e.ai.reason !== "Not requested." && <div className="notice small" style={{ marginTop: 8 }}>Local AI not used: {e.ai.reason} Showing the deterministic analysis.</div>}
      </div>
      <div className="stack">
        {e.why_not_other_markets?.length > 0 && <div><b>Why not other markets</b><ul className="plain explain">{e.why_not_other_markets.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></div>}
        {(t?.how_it_could_fail ?? e.how_it_could_fail)?.length > 0 && <div><b>How this could fail</b><ul className="plain explain">{(t?.how_it_could_fail ?? e.how_it_could_fail).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></div>}
      </div>
    </div>
  );
}

function AddButton({ a, c, onOdds }: { a: Analysis; c: Candidate; onOdds: () => void }) {
  const t = useTicket();
  const fx = a.fixture;
  const on = t.has(fx.id, c.key);
  if (!c.supported) return <span className="muted tiny">unsupported</span>;
  if (!c.price) return <button className="sm" onClick={onOdds} title="Enter the Bet365 price first">Enter odds</button>;
  if (on) return <button className="sm added" onClick={() => t.remove(fx.id, c.key)}>On ticket ✓</button>;
  return <button className={`sm ${c.qualifies ? "primary" : ""}`} disabled={!fx.prematch_eligible} onClick={() => t.add(fx.id, c.key)} title={c.qualifies ? "Add to ticket" : `Fails gates: ${c.gates_failed.join("; ")}`}>+ Add{c.qualifies ? "" : " (weak)"}</button>;
}

function Markets({ a, onOdds }: { a: Analysis; onOdds: () => void }) {
  const [fam, setFam] = useState("all");
  const [onlySupported, setOnlySupported] = useState(true);
  const cands: Candidate[] = a.candidates;
  const fams = ["all", ...Array.from(new Set(cands.map((c) => c.family)))];
  const list = cands.filter((c) => (fam === "all" || c.family === fam) && (!onlySupported || c.supported));
  const recKey = a.recommendation?.key;
  return (
    <>
      <div className="row between" style={{ marginBottom: 8 }}>
        <div className="seg">{fams.map((f) => <button key={f} className={fam === f ? "on" : ""} onClick={() => setFam(f)}>{f.replace("_", " ")}</button>)}</div>
        <label className="check"><input type="checkbox" checked={onlySupported} onChange={(e) => setOnlySupported(e.target.checked)} /> Only markets with supporting data</label>
      </div>
      <p className="muted small">Model % = model estimate with its uncertainty range (not a verified probability). History = how often the selection would have won in the home team's home matches and the away team's away matches. Implied = 1 / price. Evidence (0–85) + price (0–15) = score. See docs/SCORING.md.</p>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Selection</th><th className="num">Model</th><th className="num">Range</th><th className="num">Home hist.</th><th className="num">Away hist.</th><th className="num">Price</th><th className="num">Implied</th><th className="num">Edge</th><th className="num">Evidence</th><th className="num">Score</th><th>Verdict</th><th></th></tr></thead>
          <tbody>
            {list.map((c) => (
              <tr key={c.key} className={c.supported ? "" : "dim"} style={c.key === recKey ? { background: "var(--accent-soft)" } : undefined}>
                <td><div className="teams">{c.label}{c.key === recKey && <> <Chip tone="good">recommended</Chip></>}</div><div className="muted tiny">{c.market_name}{c.flags.length ? ` · ${c.flags[0]}` : ""}</div></td>
                <td className="num">{c.probability_pct != null ? `${c.probability_pct}%` : "—"}</td>
                <td className="num muted">{c.range_pct ? `${c.range_pct[0]}–${c.range_pct[1]}` : ""}</td>
                <td className="num">{hr(c.hit_rates.home_team_home)}</td>
                <td className="num">{hr(c.hit_rates.away_team_away)}</td>
                <td className="num nowrap">{c.price ? <span title={`${c.price.bookmaker} · ${c.price.source === "manual" ? "manual entry" : "dataset snapshot"} · ${c.price.checked_at}`}><b>{fmtOdds(c.price.odds)}</b> <span className="muted tiny">{c.price.source === "manual" ? "manual" : "snap"}</span></span> : <span className="muted">—</span>}</td>
                <td className="num">{pct(c.implied_probability)}</td>
                <td className="num" style={{ color: c.edge == null ? undefined : c.edge > 0 ? "var(--good)" : "var(--bad)" }}>{c.edge == null ? "—" : `${c.edge > 0 ? "+" : ""}${Math.round(100 * c.edge)}`}</td>
                <td className="num">{c.supported ? c.score.evidence : "—"}</td>
                <td className="num"><b>{c.supported ? c.score.total : "—"}</b></td>
                <td style={{ maxWidth: 260 }}>{!c.supported ? <span className="muted small">{c.unsupported_reason}</span> : c.qualifies ? <Chip tone={c.tier === "strong" ? "good" : c.tier === "acceptable" ? "info" : "warn"}>{c.tier} · {c.confidence}</Chip> : <span className="small muted">{c.gates_failed[0]}</span>}</td>
                <td className="right"><AddButton a={a} c={c} onOdds={onOdds} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function StatLine({ label, s, unit = "" }: { label: string; s: { mean: number | null; n: number; of: number; completeness: number; warning: string | null }; unit?: string }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="num"><b>{s.mean ?? "—"}</b>{unit}</td>
      <td className="num muted">{s.n}/{s.of}</td>
      <td className="num muted">{Math.round(100 * s.completeness)}%</td>
      <td className="small" style={{ color: s.warning ? "var(--warn)" : undefined }}>{s.warning ?? ""}</td>
    </tr>
  );
}

function RateLine({ label, r }: { label: string; r: { k: number; n: number; rate: number | null; warning: string | null } }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="num"><b>{r.rate == null ? "—" : pct(r.rate)}</b></td>
      <td className="num muted">{r.k}/{r.n}</td>
      <td></td>
      <td className="small" style={{ color: r.warning ? "var(--warn)" : undefined }}>{r.warning ?? ""}</td>
    </tr>
  );
}

function TeamProfile({ name, p, side }: { name: string; p: Analysis; side: "home" | "away" }) {
  const v = p.venue_form;
  const g = p.goals_venue;
  const m = p.misc_venue;
  const venue = side === "home" ? "at home" : "away";
  return (
    <div>
      <div className="row between" style={{ marginBottom: 6 }}><h3>{name}</h3><span className="muted small">{p.matches} matches in sample</span></div>
      <table className="tbl">
        <tbody>
          <tr><td>Last 5</td><td colSpan={2}><FormSeq seq={p.form5.sequence} /></td><td colSpan={2} className="small">{p.form5.w}W {p.form5.d}D {p.form5.l}L · goals {p.form5.gf}-{p.form5.ga} · {p.form5.ppg} ppg · win {pct(p.form5.win_pct)}</td></tr>
          <tr><td>Last 10</td><td colSpan={2}><FormSeq seq={p.form10.sequence} /></td><td colSpan={2} className="small">{p.form10.w}W {p.form10.d}D {p.form10.l}L · goals {p.form10.gf}-{p.form10.ga} · avg {p.form10.gf_avg}/{p.form10.ga_avg} {p.form10.warning ? `· ${p.form10.warning}` : ""}</td></tr>
          <tr><td>{venue}</td><td colSpan={4} className="small">{v.n} matches · {v.w}W {v.d}D {v.l}L · {v.ppg ?? "—"} ppg · scored {v.gf_avg ?? "—"} · conceded {v.ga_avg ?? "—"} per game</td></tr>
        </tbody>
      </table>
      <table className="tbl" style={{ marginTop: 8 }}>
        <thead><tr><th>{venue}</th><th className="num">Value</th><th className="num">n</th><th className="num">Complete</th><th>Warning</th></tr></thead>
        <tbody>
          <StatLine label="Goals scored / game" s={g.gf} />
          <StatLine label="Goals conceded / game" s={g.ga} />
          <RateLine label="Over 1.5" r={g.over15} />
          <RateLine label="Over 2.5" r={g.over25} />
          <RateLine label="Over 3.5" r={g.over35} />
          <RateLine label="Under 2.5" r={g.under25} />
          <RateLine label="Both teams scored" r={g.btts} />
          <RateLine label="Clean sheets" r={g.clean_sheet} />
          <RateLine label="Failed to score" r={g.failed_to_score} />
          <RateLine label="First-half goal" r={g.ht_goal} />
          <StatLine label="1st-half goals / game" s={g.first_half_goals} />
          <StatLine label="2nd-half goals / game" s={g.second_half_goals} />
          <StatLine label="Shots for" s={m.shots_for} />
          <StatLine label="Shots against" s={m.shots_against} />
          <StatLine label="Shots on target for" s={m.sot_for} />
          <StatLine label="Shots on target against" s={m.sot_against} />
          <RateLine label="Scored in (all matches)" r={p.scoring_consistency} />
        </tbody>
      </table>
    </div>
  );
}

function GoalsChart({ name, recent }: { name: string; recent: { date: string; opponent: string; gf: number; ga: number; venue: string }[] }) {
  const data = [...recent].reverse().map((r) => ({ label: `${r.venue === "H" ? "v" : "@"} ${r.opponent.slice(0, 10)}`, Scored: r.gf, Conceded: r.ga }));
  return (
    <div>
      <div className="small muted" style={{ marginBottom: 4 }}>{name}: last {data.length} matches (oldest → newest)</div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -24, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 3" stroke="var(--line)" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: "var(--muted)" }} interval={0} angle={-30} textAnchor="end" height={48} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--muted)" }} />
          <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", fontSize: 12 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="Scored" fill="var(--accent)" radius={[2, 2, 0, 0]} />
          <Bar dataKey="Conceded" fill="var(--bad)" radius={[2, 2, 0, 0]} opacity={0.75} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Teams({ a }: { a: Analysis }) {
  const s = a.samples;
  return (
    <div className="stack">
      <div className="notice small">
        Sample: {a.fixture.home} {s.home.n} matches ({Object.entries(s.home.competitions).map(([k, v]) => `${k} ${v}`).join(", ")}) · {a.fixture.away} {s.away.n} matches ({Object.entries(s.away.competitions).map(([k, v]) => `${k} ${v}`).join(", ")}).
        {s.cross_league && " Teams play in different leagues: comparisons across leagues are approximate."}
        {" "}Only 2026/27 data is available (no prior seasons), so promoted teams and early-season samples are shrunk toward league average.
      </div>
      <div className="grid g2">
        <GoalsChart name={a.fixture.home} recent={a.profiles.home.recent} />
        <GoalsChart name={a.fixture.away} recent={a.profiles.away.recent} />
      </div>
      <div className="grid g2">
        <TeamProfile name={a.fixture.home} p={a.profiles.home} side="home" />
        <TeamProfile name={a.fixture.away} p={a.profiles.away} side="away" />
      </div>
      <div className="grid g2">
        {(["home", "away"] as const).map((side) => (
          <div key={side}>
            <h3 style={{ marginBottom: 6 }}>{a.fixture[side]} — last 10</h3>
            <table className="tbl"><thead><tr><th>Date</th><th>Comp</th><th></th><th>Opponent</th><th className="num">FT</th><th className="num">HT</th><th className="num">Corners</th><th className="num">Cards</th></tr></thead>
              <tbody>{a.profiles[side].recent.map((r: Analysis, i: number) => (
                <tr key={i}><td className="num nowrap">{r.date.slice(5)}</td><td className="tiny muted">{r.competition.split("_").slice(0, 2).join(" ")}</td><td>{r.venue}</td><td>{r.opponent}</td><td className="num"><b>{r.gf}-{r.ga}</b> <span className={`chip ${r.result === "W" ? "good" : r.result === "L" ? "bad" : ""}`}>{r.result}</span></td><td className="num muted">{r.ht ?? "—"}</td><td className="num muted">{r.corners ?? "—"}</td><td className="num muted">{r.cards ?? "—"}</td></tr>
              ))}</tbody></table>
          </div>
        ))}
      </div>
    </div>
  );
}

function CountModelBox({ m, title }: { m: Analysis; title: string }) {
  if (!m.available) return <div className="notice warn"><b>{title}:</b> {m.reason}</div>;
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="row between"><h3>{title}</h3><span className="muted tiny">{m.label}</span></div>
      <dl className="kv" style={{ marginTop: 8 }}>
        <dt>Expected</dt><dd><b>{m.expected_home} + {m.expected_away} = {m.expected_total}</b> (range {m.expected_total_range[0]}–{m.expected_total_range[1]})</dd>
        <dt>Samples</dt><dd>home {m.n_home}, away {m.n_away} matches{m.venue_specific ? " (venue-specific)" : " (all venues)"}</dd>
        <dt>Inputs</dt><dd>home for {m.inputs.home_for} / against {m.inputs.home_against}; away for {m.inputs.away_for} / against {m.inputs.away_against}</dd>
        <dt>League</dt><dd>{m.league.total_mean} per match, variance/mean {m.dispersion} ({m.league.n} matches, {m.league.source})</dd>
      </dl>
      {m.rule_note && <p className="small muted" style={{ marginTop: 6 }}>{m.rule_note}</p>}
      <p className="small muted">{m.referee}</p>
    </div>
  );
}

function CornersCards({ a }: { a: Analysis }) {
  const hp = a.profiles.home, ap = a.profiles.away;
  return (
    <div className="stack">
      <div className="grid g2">
        <CountModelBox m={a.corners} title="Corners model" />
        <CountModelBox m={a.cards} title="Cards model" />
      </div>
      <div className="grid g2">
        {([["home", hp], ["away", ap]] as const).map(([side, p]) => (
          <div key={side}>
            <h3 style={{ marginBottom: 6 }}>{a.fixture[side]} ({side === "home" ? "home matches" : "away matches"})</h3>
            <table className="tbl"><thead><tr><th>Statistic</th><th className="num">Avg</th><th className="num">n</th><th className="num">Complete</th><th>Warning</th></tr></thead>
              <tbody>
                <StatLine label="Corners for" s={p.misc_venue.corners_for} />
                <StatLine label="Corners against" s={p.misc_venue.corners_against} />
                <StatLine label="Corners, match total" s={p.misc_venue.corners_total} />
                <StatLine label="Corners 1st half, total" s={p.misc_venue.corners_1h_total} />
                <StatLine label="Yellow cards (team)" s={p.misc_venue.yellow_for} />
                <StatLine label="Yellow cards (opponent)" s={p.misc_venue.yellow_against} />
                <StatLine label="Red cards (team)" s={p.misc_venue.red_for} />
                <StatLine label="Cards, match total" s={p.misc_venue.cards_total} />
                <StatLine label="Fouls committed" s={p.misc_venue.fouls_for} />
                <StatLine label="Fouls suffered" s={p.misc_venue.fouls_against} />
              </tbody></table>
            <div className="small" style={{ marginTop: 6 }}>
              Last {p.corners_last5.n} matches with corner data: {p.corners_last5.values.map((x: Analysis) => `${x.for}-${x.against}`).join(", ") || "none"}
              {p.corners_last5.warning && <span style={{ color: "var(--warn)" }}> · {p.corners_last5.warning}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface MarketDef { market: string; name: string; selections: string[]; needs_line: boolean }

function OddsTab({ a, onSaved }: { a: Analysis; onSaved: () => void }) {
  const { data: markets } = useFetch<MarketDef[]>("/api/markets");
  const fx = a.fixture;
  const [form, setForm] = useState({ bookmaker: "Bet365", market: "OU", selection: "over", line: "2.5", odds: "", checked_at: nowLocalInput(), note: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { data: odds, reload } = useFetch<Analysis[]>(`/api/odds?match_id=${enc(fx.id)}`, [fx.id]);
  const def = markets?.find((m) => m.market === form.market);
  const save = async () => {
    setErr(null); setMsg(null);
    try {
      const r = await api<Analysis>("/api/odds", { method: "POST", json: { match_id: fx.id, bookmaker: form.bookmaker, market: form.market, selection: form.selection, line: def?.needs_line ? Number(form.line) : null, odds: Number(form.odds), checked_at: form.checked_at, note: form.note || null } });
      setMsg(r.notice); setForm({ ...form, odds: "" }); reload(); onSaved();
    } catch (e) { setErr((e as Error).message); }
  };
  const del = async (oid: number) => { await api(`/api/odds/${oid}`, { method: "DELETE" }); reload(); onSaved(); };
  const manual = (odds ?? []).filter((o) => o.source === "manual");
  const snap = (odds ?? []).filter((o) => o.source !== "manual");
  return (
    <div className="stack">
      <div className="notice info small">Enter prices exactly as shown by your bookmaker, with the time you checked. MatchEdge never logs in to Bet365, stores no credentials and never treats your entries as verified live odds. Dataset snapshot prices (Flashscore pre-match quotes published by Open-Matchday) are shown separately and labelled.</div>
      <details open className="panel" style={{ padding: 10 }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>Paste from Bet365</summary>
        <div style={{ marginTop: 8 }}><PasteOdds matchId={fx.id} onSaved={() => { reload(); onSaved(); }} /></div>
      </details>
      <h3>Enter one price</h3>
      <div className="form-grid">
        <label className="f">Bookmaker<input value={form.bookmaker} onChange={(e) => setForm({ ...form, bookmaker: e.target.value })} /></label>
        <label className="f">Market<select value={form.market} onChange={(e) => { const m = markets?.find((x) => x.market === e.target.value); setForm({ ...form, market: e.target.value, selection: m?.selections[0] ?? "" }); }}>{markets?.map((m) => <option key={m.market} value={m.market}>{m.name}</option>)}</select></label>
        <label className="f">Selection<select value={form.selection} onChange={(e) => setForm({ ...form, selection: e.target.value })}>{def?.selections.map((s) => <option key={s} value={s}>{s === "home" ? `home (${fx.home})` : s === "away" ? `away (${fx.away})` : s}</option>)}</select></label>
        {def?.needs_line && <label className="f">Line {form.market === "AH" ? "(selected team's handicap)" : ""}<input type="number" step="0.25" value={form.line} onChange={(e) => setForm({ ...form, line: e.target.value })} /></label>}
        <label className="f">Decimal odds<input type="number" step="0.01" min="1.01" value={form.odds} onChange={(e) => setForm({ ...form, odds: e.target.value })} placeholder="1.65" /></label>
        <label className="f">Checked at (Belgrade)<input value={form.checked_at} onChange={(e) => setForm({ ...form, checked_at: e.target.value })} /></label>
        <label className="f">Note<input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></label>
        <button className="primary" onClick={save} disabled={!form.odds}>Save price</button>
      </div>
      {msg && <div className="notice good small">{msg}</div>}
      <ErrorBox error={err} />
      <h3>Your entries ({manual.length})</h3>
      {manual.length === 0 ? <div className="muted small">None yet.</div> : (
        <table className="tbl"><thead><tr><th>Market</th><th>Selection</th><th className="num">Line</th><th className="num">Odds</th><th>Bookmaker</th><th>Checked (UTC)</th><th></th></tr></thead>
          <tbody>{manual.map((o) => <tr key={o.id}><td>{o.market}</td><td>{o.selection}</td><td className="num">{o.line ?? ""}</td><td className="num"><b>{fmtOdds(o.odds)}</b></td><td>{o.bookmaker}</td><td className="num small">{o.checked_at}</td><td><button className="sm ghost danger" onClick={() => del(o.id)}>Delete</button></td></tr>)}</tbody></table>
      )}
      <PriceHistory matchId={fx.id} />
      <details><summary className="muted small">Dataset snapshot prices ({snap.length}) — reference only, not live</summary>
        <table className="tbl" style={{ marginTop: 6 }}><thead><tr><th>Market</th><th>Selection</th><th className="num">Line</th><th className="num">Odds</th><th>Bookmaker</th><th>Snapshot (UTC)</th></tr></thead>
          <tbody>{snap.slice(0, 200).map((o) => <tr key={o.id}><td>{o.market}</td><td>{o.selection}</td><td className="num">{o.line ?? ""}</td><td className="num">{fmtOdds(o.odds)}</td><td>{o.bookmaker}</td><td className="num small">{o.checked_at}</td></tr>)}</tbody></table>
      </details>
    </div>
  );
}

function PriceHistory({ matchId }: { matchId: string }) {
  const { data } = useFetch<Analysis[]>(`/api/odds/history?match_id=${enc(matchId)}`, [matchId]);
  const groups = new Map<string, Analysis[]>();
  (data ?? []).filter((r) => r.bookmaker.toLowerCase() === "bet365").forEach((r) => {
    const k = `${r.market} ${r.selection} ${r.line ?? ""}`.trim();
    groups.set(k, [...(groups.get(k) ?? []), r]);
  });
  const moved = [...groups.entries()].filter(([, v]) => v.length > 1);
  return (
    <details>
      <summary className="muted small">Bet365 price movement from daily snapshots ({moved.length} selections moved)</summary>
      {moved.length === 0 ? <p className="small muted" style={{ marginTop: 6 }}>No movement recorded yet. Each import archives changed prices; history builds up day by day.</p> : (
        <table className="tbl" style={{ marginTop: 6 }}><thead><tr><th>Selection</th><th>Price path (oldest → newest)</th><th className="num">Change</th></tr></thead>
          <tbody>{moved.map(([k, v]) => {
            const first = v[0].odds, last = v[v.length - 1].odds;
            return <tr key={k}><td>{k}</td><td className="num small">{v.map((x) => `${fmtOdds(x.odds)} (${x.captured_at.slice(5, 10)})`).join(" → ")}</td><td className="num" style={{ color: last < first ? "var(--bad)" : "var(--good)" }}>{last < first ? "shortened" : "drifted"} {Math.round(100 * (last / first - 1))}%</td></tr>;
          })}</tbody></table>
      )}
    </details>
  );
}

function ResearchTab({ a, onSaved }: { a: Analysis; onSaved: () => void }) {
  const fx = a.fixture;
  const blank = { url: "", category: "statistics", statistic: "", value: "", notes: "", checked_at: nowLocalInput(), reliability: "medium", impact: "neutral", related_market: "" };
  const [f, setF] = useState(blank);
  const [err, setErr] = useState<string | null>(null);
  const markets = useMemo(() => (a.candidates as Candidate[]).filter((c) => c.supported).map((c) => [c.key, c.label] as const), [a.candidates]);
  const save = async () => {
    setErr(null);
    try { await api("/api/research", { method: "POST", json: { match_id: fx.id, ...f, url: f.url || null, related_market: f.related_market || null } }); setF({ ...blank, checked_at: nowLocalInput() }); onSaved(); }
    catch (e) { setErr((e as Error).message); }
  };
  const del = async (rid: number) => { await api(`/api/research/${rid}`, { method: "DELETE" }); onSaved(); };
  return (
    <div className="stack">
      <div className="grid g2">
        <div>
          <h3 style={{ marginBottom: 6 }}>Research links</h3>
          <p className="small muted">MatchEdge does not scrape these sites. Open them yourself, then record what you found below with the URL and the time you checked.</p>
          <ul className="plain">{a.links.map((l: Analysis) => <li key={l.url}><a href={l.url} target="_blank" rel="noreferrer">{l.name}</a> <span className="muted small">— {l.note}</span></li>)}</ul>
        </div>
        <div>
          <h3 style={{ marginBottom: 6 }}>Add research entry</h3>
          <div className="form-grid">
            <label className="f" style={{ gridColumn: "1 / -1" }}>Source URL<input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://footiqo.com/…" /></label>
            <label className="f">Category<select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{["statistics", "lineup", "injury", "news", "referee", "weather", "other"].map((x) => <option key={x}>{x}</option>)}</select></label>
            <label className="f">Statistic<input value={f.statistic} onChange={(e) => setF({ ...f, statistic: e.target.value })} placeholder="Over 2.5 in last 10 H2H" /></label>
            <label className="f">Value<input value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} placeholder="7/10" /></label>
            <label className="f">Checked at<input value={f.checked_at} onChange={(e) => setF({ ...f, checked_at: e.target.value })} /></label>
            <label className="f">Reliability<select value={f.reliability} onChange={(e) => setF({ ...f, reliability: e.target.value })}><option>high</option><option>medium</option><option>low</option></select></label>
            <label className="f">Effect<select value={f.impact} onChange={(e) => setF({ ...f, impact: e.target.value })}><option value="neutral">neutral / context</option><option value="supports">supports a market</option><option value="contradicts">contradicts a market</option></select></label>
            <label className="f">Related market<select value={f.related_market} onChange={(e) => setF({ ...f, related_market: e.target.value })}><option value="">(none)</option>{markets.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
            <label className="f" style={{ gridColumn: "1 / -1" }}>Notes<textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></label>
          </div>
          <div className="row" style={{ marginTop: 8 }}><button className="primary" onClick={save}>Save entry</button><span className="muted small">Lineup/injury entries (medium+ reliability, not "supports") reject the match until resolved.</span></div>
          <ErrorBox error={err} />
        </div>
      </div>
      <h3>Evidence for this match ({a.evidence.length})</h3>
      {a.evidence.length === 0 ? <div className="muted small">No manual research recorded. The analysis uses dataset statistics only.</div> : (
        <table className="tbl"><thead><tr><th>Checked</th><th>Category</th><th>Statistic</th><th>Value</th><th>Reliability</th><th>Effect</th><th>Source</th><th></th></tr></thead>
          <tbody>{a.evidence.map((r: Analysis) => (
            <tr key={r.id}><td className="num small nowrap">{r.checked_at.replace("T", " ").slice(0, 16)}</td><td>{r.category}</td><td>{r.statistic}<div className="muted tiny">{r.notes}</div></td><td>{r.value}</td><td><Chip tone={r.reliability === "high" ? "good" : r.reliability === "low" ? "warn" : "info"}>{r.reliability}</Chip></td><td>{r.impact}{r.related_market ? <div className="muted tiny">{r.related_market}</div> : null}</td><td>{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{new URL(r.url).hostname}</a> : <span className="muted">no URL</span>}</td><td><button className="sm ghost danger" onClick={() => del(r.id)}>Delete</button></td></tr>
          ))}</tbody></table>
      )}
    </div>
  );
}

function FixtureTab({ a, onSaved }: { a: Analysis; onSaved: () => void }) {
  const fx: Fixture = a.fixture;
  const [f, setF] = useState({ kickoff_local: fx.kickoff_local ?? "", status: "", verified: fx.verified, verification_url: fx.verification_url ?? "", note: fx.override_note ?? "" });
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const save = async () => {
    setErr(null); setOk(false);
    try { await api(`/api/matches/${enc(fx.id)}/override`, { method: "PUT", json: { kickoff_local: f.kickoff_local || null, status: f.status || null, verified: f.verified, verification_url: f.verification_url || null, note: f.note || null } }); setOk(true); onSaved(); }
    catch (e) { setErr((e as Error).message); }
  };
  const reset = async () => { await api(`/api/matches/${enc(fx.id)}/override`, { method: "DELETE" }); onSaved(); };
  return (
    <div className="grid g2">
      <div>
        <h3 style={{ marginBottom: 6 }}>Kickoff and status</h3>
        <dl className="kv">
          <dt>Dataset date/time</dt><dd>{fx.date} · {a.fixture.kickoff_utc ? `${a.fixture.kickoff_utc} UTC` : "time not supplied"}</dd>
          <dt>Shown as</dt><dd>{fx.kickoff_local ?? "—"} {fx.timezone}</dd>
          <dt>Certainty</dt><dd>{TIME_LABEL[fx.time_certainty] ?? fx.time_certainty}</dd>
          <dt>Notes</dt><dd>{fx.time_notes.join(" ")}</dd>
          <dt>Dataset status</dt><dd>{fx.dataset_status}</dd>
          <dt>Source</dt><dd>{fx.source}</dd>
        </dl>
        <p className="small muted" style={{ marginTop: 8 }}>The dataset can be wrong about times and does not mark postponements reliably. Check the official competition website (link in the Research tab) and correct it here.</p>
      </div>
      <div>
        <h3 style={{ marginBottom: 6 }}>Correct / verify</h3>
        <div className="form-grid">
          <label className="f">Kickoff (Belgrade, YYYY-MM-DD HH:MM)<input value={f.kickoff_local} onChange={(e) => setF({ ...f, kickoff_local: e.target.value })} /></label>
          <label className="f">Status<select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">(as in dataset)</option><option value="scheduled">scheduled</option><option value="postponed">postponed</option><option value="cancelled">cancelled</option><option value="abandoned">abandoned</option></select></label>
          <label className="f" style={{ gridColumn: "1 / -1" }}>Official URL used to verify<input value={f.verification_url} onChange={(e) => setF({ ...f, verification_url: e.target.value })} placeholder="https://www.uefa.com/…" /></label>
          <label className="check"><input type="checkbox" checked={f.verified} onChange={(e) => setF({ ...f, verified: e.target.checked })} /> I checked date, time and status on the official site</label>
          <label className="f" style={{ gridColumn: "1 / -1" }}>Note<input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
        </div>
        <div className="row" style={{ marginTop: 8 }}><button className="primary" onClick={save}>Save</button><button className="ghost" onClick={reset}>Reset to dataset</button></div>
        {ok && <div className="notice good small" style={{ marginTop: 6 }}>Saved.</div>}
        <ErrorBox error={err} />
      </div>
    </div>
  );
}

function Components({ title, c }: { title: string; c: Record<string, { points: number; max: number; why: string }> }) {
  return (
    <div>
      <h3 style={{ marginBottom: 6 }}>{title}</h3>
      <table className="tbl"><tbody>{Object.entries(c).map(([k, v]) => (
        <tr key={k}><td className="nowrap">{k.replace(/_/g, " ")}</td><td className="num nowrap"><b>{v.points}</b> / {v.max}</td><td className="small muted">{v.why}</td></tr>
      ))}</tbody></table>
    </div>
  );
}

function ModelTab({ a }: { a: Analysis }) {
  const m = a.model;
  return (
    <div className="stack">
      <div className="grid g2">
        <Components title={`Match research score: ${a.research_score.score}`} c={a.research_score.components} />
        <Components title={`Data quality: ${a.data_quality.score}`} c={a.data_quality.components} />
      </div>
      {m.details?.ml && (
        <div>
          <h3 style={{ marginBottom: 6 }}>Trained ML model vs statistical engine</h3>
          <table className="tbl"><thead><tr><th>Market</th><th className="num">Statistical engine</th><th className="num">ML ({m.details.ml.variant === "market" ? "stats + Bet365 odds" : "stats only"}) — used</th></tr></thead>
            <tbody>{[["home", "Home win"], ["draw", "Draw"], ["away", "Away win"], ["over_2.5", "Over 2.5"], ["btts_yes", "Both teams score"]].map(([k, l]) => (
              <tr key={k}><td>{l}</td><td className="num muted">{pct(m.details.ml.statistical_engine[k])}</td><td className="num"><b>{pct(m.details.ml.ml[k])}</b></td></tr>
            ))}</tbody></table>
          <p className="tiny muted" style={{ marginTop: 4 }}>Out of sample the ML was more accurate than the statistical engine (see <Link to="/model">Model lab</Link>). Other goal markets use expected goals re-fitted to the ML: {m.details.ml.lambda_home}–{m.details.ml.lambda_away}.</p>
        </div>
      )}
      {!m.available ? <div className="notice warn">Goal model: {m.reason}</div> : (
        <div className="grid g2">
          <div>
            <h3 style={{ marginBottom: 6 }}>Poisson model — {m.label}</h3>
            <table className="tbl"><tbody>
              {Object.entries(m.probabilities_pct as Record<string, number>).map(([k, v]) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="num"><b>{v}%</b></td><td className="num muted">{(m.ranges_pct[k] as number[]).join("–")}%</td></tr>)}
            </tbody></table>
          </div>
          <div>
            <h3 style={{ marginBottom: 6 }}>Inputs</h3>
            <dl className="kv">
              <dt>Baseline</dt><dd>home {m.details.baseline.home_goals}, away {m.details.baseline.away_goals} goals ({m.details.baseline.n_matches} matches, {m.details.baseline.source})</dd>
              <dt>{a.fixture.home}</dt><dd>attack {m.details.applied.home_attack}, defence {m.details.applied.home_defence} (n={m.details.home.n}, effective {m.details.home.n_eff})</dd>
              <dt>{a.fixture.away}</dt><dd>attack {m.details.applied.away_attack}, defence {m.details.applied.away_defence} (n={m.details.away.n}, effective {m.details.away.n_eff})</dd>
              <dt>First half</dt><dd>{m.first_half?.available ? `${m.first_half.expected_goals} expected goals (share ${m.first_half.share_of_goals_before_ht}, ${m.first_half.baseline_source})` : m.first_half?.reason}</dd>
              <dt>Settings</dt><dd className="small">{Object.entries(m.details.settings).map(([k, v]) => `${k}=${v}`).join(", ")}</dd>
            </dl>
            {m.details.notes.length > 0 && <ul className="plain small" style={{ marginTop: 6 }}>{m.details.notes.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>}
          </div>
        </div>
      )}
      <div>
        <h3 style={{ marginBottom: 6 }}>Missing information</h3>
        <ul className="plain small">{a.decision.missing_information.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
      </div>
      <p className="tiny muted">{a.dataset.attribution} <Link to="/data">Data sources</Link></p>
    </div>
  );
}
