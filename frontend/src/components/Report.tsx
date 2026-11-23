import { Link } from "react-router-dom";
import { enc, type Report } from "../api";
import { fmtOdds, smallPct } from "../format";
import { Chip, Panel, StatusChip } from "./ui";

function LegTable({ legs }: { legs: Report[] }) {
  return (
    <table className="tbl">
      <thead><tr><th>Match</th><th>Selection</th><th className="num">Odds</th><th className="num">Model</th><th>Tier</th></tr></thead>
      <tbody>{legs.map((l) => (
        <tr key={l.match_id + l.key}><td>{l.match_label}<div className="muted tiny">{l.kickoff_local}</div></td><td>{l.label}</td><td className="num"><b>{fmtOdds(l.odds)}</b></td><td className="num">{l.probability_pct}%</td><td><StatusChip value={l.tier} /></td></tr>
      ))}</tbody>
    </table>
  );
}

export default function ReportView({ r }: { r: Report }) {
  const s = r.summary;
  const ev = r.evaluation;
  return (
    <div className="stack">
      <Panel title="Ticket summary" sub={`${r.mode === "auto" ? "auto-built" : "your selections"} · ${r.analysed_matches} matches analysed`}>
        <div className="grid g4">
          <div><div className="muted small">Requested odds</div><div className="big-odds">{fmtOdds(s.requested_odds)}</div></div>
          <div><div className="muted small">Actual combined odds</div><div className="big-odds" style={{ color: s.target_reached ? "var(--good)" : "var(--warn)" }}>{fmtOdds(s.combined_odds)}</div><div className="small">{s.target_reached ? "target reached" : "below target — not padded"}</div></div>
          <div><div className="muted small">Selections</div><div className="big-odds">{s.n_selections}</div><div className="small muted">{s.dates.join(", ")}</div></div>
          <div><div className="muted small">Naive model estimate (all legs win)</div><div className="big-odds">{smallPct(s.model_probability_all_win)}</div><div className="small muted">bookmaker implies {smallPct(s.bookmaker_implied_probability)}</div></div>
        </div>
        <div className="sep" />
        <dl className="kv small">
          <dt>Competitions</dt><dd>{s.competitions.join(", ") || "—"}</dd>
          <dt>Price source</dt><dd>{s.price_sources.join(", ") || "—"} — {s.price_note}</dd>
          <dt>Data freshness</dt><dd>Open-Matchday build {s.data_freshness.dataset_generated_utc ?? "unknown"} ({s.data_freshness.age_days ?? "?"} days old)</dd>
          <dt>Probability note</dt><dd>{s.model_probability_note}</dd>
        </dl>
      </Panel>

      <div className={`notice ${s.target_reached && !ev.weak_legs ? "good" : "warn"}`}><b>Final opinion.</b> {r.final_opinion}</div>
      {r.ai?.used && <Panel title="Local AI summary" sub={r.ai.model}><p>{r.ai.text.summary}</p><p><b>{r.ai.text.final_opinion}</b></p></Panel>}
      {r.ai && !r.ai.used && r.ai.reason !== "Not requested." && <div className="notice small">Local AI not used: {r.ai.reason}</div>}

      {(ev.errors.length > 0 || ev.warnings.length > 0) && (
        <div className={`notice ${ev.errors.length ? "bad" : "warn"}`}>
          {ev.errors.length > 0 && <><b>Errors</b><ul>{ev.errors.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul></>}
          {ev.warnings.length > 0 && <details open={ev.warnings.length < 6}><summary><b>{ev.warnings.length} warnings</b></summary><ul>{ev.warnings.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul></details>}
        </div>
      )}

      <Panel title="Main selections" sub={`${r.selections.length}`}>
        {r.selections.length === 0 ? <div className="muted">No selection passed the gates with a price. Enter Bet365 odds for qualifying markets on the match pages.</div> : (
          <div className="stack">
            {r.selections.map((d: Report, i: number) => (
              <div key={d.match_id + d.key} className="panel" style={{ padding: 12 }}>
                <div className="row between">
                  <div>
                    <div className="muted small">{i + 1}. {d.competition_name} · {d.kickoff_local ?? "time TBC"}{d.verified ? "" : " · unverified fixture"}</div>
                    <div style={{ fontSize: 15, fontWeight: 650 }}><Link to={`/match/${enc(d.match_id)}`}>{d.match_label}</Link> — {d.label}</div>
                  </div>
                  <div className="row">
                    <span className="big-odds" style={{ fontSize: 22 }}>{fmtOdds(d.odds)}</span>
                    <div className="stack" style={{ gap: 3 }}>
                      <Chip tone={d.odds_source === "manual" ? "good" : "warn"}>{d.bookmaker} · {d.odds_source === "manual" ? "manual entry" : "snapshot"}</Chip>
                      <span className="tiny muted">checked {String(d.odds_checked_at).replace("T", " ").slice(0, 16)} UTC</span>
                    </div>
                  </div>
                </div>
                <div className="row small" style={{ margin: "6px 0" }}>
                  <span>Model <b>{d.probability_pct}%</b> <span className="muted">({d.range_pct?.join("–")}%)</span></span>
                  <span>Implied <b>{smallPct(d.implied_probability)}</b></span>
                  <span>Confidence <StatusChip value={d.confidence ?? "none"} /></span>
                  <span>Data quality <b>{Math.round(d.data_quality)}</b> ({d.data_quality_label})</span>
                  <span>Match <StatusChip value={d.match_status} /></span>
                </div>
                <ul className="plain small explain">{d.reasoning.map((x: string, j: number) => <li key={j}>{x}</li>)}</ul>
                <div className="small" style={{ marginTop: 6 }}><b>Main risk:</b> {d.main_risk}</div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div className="grid g2">
        <Panel title="Biggest risks">
          {r.biggest_risks.length === 0 ? <div className="muted">—</div> : <ol style={{ margin: 0, paddingLeft: 18 }}>{r.biggest_risks.map((b: Report, i: number) => <li key={i} style={{ marginBottom: 6 }}><b>{b.match_label}: {b.label}</b> ({b.probability_pct}% model) — {b.why}</li>)}</ol>}
        </Panel>
        <Panel title="Alternative ticket" sub="fewer, better-supported legs">
          {r.alternative_ticket ? <><div className="row" style={{ marginBottom: 6 }}><span className="big-odds" style={{ fontSize: 20 }}>{fmtOdds(r.alternative_ticket.evaluation.combined_odds)}</span><span className="muted small">{r.alternative_ticket.evaluation.n_selections} legs · naive estimate {smallPct(r.alternative_ticket.evaluation.model_probability_all_win)}</span></div><LegTable legs={r.alternative_ticket.legs} /></> : <div className="muted">Not enough selections for a smaller alternative.</div>}
        </Panel>
      </div>

      {r.padded_version && (
        <Panel title="What reaching the target would take" sub="not recommended">
          <div className="notice warn small" style={{ marginBottom: 8 }}>{r.padded_version.warning} Combined {fmtOdds(r.padded_version.evaluation.combined_odds)}, naive estimate {smallPct(r.padded_version.evaluation.model_probability_all_win)}.</div>
          <LegTable legs={r.padded_version.legs} />
        </Panel>
      )}

      <Panel title="Rejected and flagged matches" sub={`${r.rejected_matches.length} analysed but not selected`} tight>
        <div className="tbl-wrap" style={{ maxHeight: 420 }}>
          <table className="tbl"><thead><tr><th>Match</th><th>Status</th><th>Why</th><th>Other markets</th></tr></thead>
            <tbody>{r.rejected_matches.map((m: Report) => (
              <tr key={m.match_id}><td><Link to={`/match/${enc(m.match_id)}`}>{m.match_label}</Link><div className="muted tiny">{m.competition} · {m.kickoff_local}</div></td><td><StatusChip value={m.status} /></td><td className="small">{m.reasons.join(" · ")}</td><td className="small">{m.alternatives.join(", ") || "—"}</td></tr>
            ))}</tbody></table>
        </div>
      </Panel>
      <p className="tiny muted">{r.attribution}</p>
    </div>
  );
}
