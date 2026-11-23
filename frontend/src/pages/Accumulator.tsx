import { useState } from "react";
import { Link } from "react-router-dom";
import { api, enc, qs, type Report, type Summary } from "../api";
import ReportView from "../components/Report";
import { Chip, CompetitionPicker, DateRange, Empty, ErrorBox, Loading, Panel, StatusChip, useFetch, usePersistent } from "../components/ui";
import { fmtOdds, smallPct, todayLocal, addDays } from "../format";
import { useTicket } from "../ticket";

const PRESETS = [10, 30, 50, 110, 150, 300];

function Slip({ onReport, busyReport }: { onReport: () => void; busyReport: boolean }) {
  const t = useTicket();
  const ev = t.evaluation;
  const [name, setName] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const progress = t.combined ? Math.min(100, (Math.log(t.combined) / Math.log(t.target)) * 100) : 0;
  const save = async () => {
    setErr(null); setSaved(null);
    try {
      const r = await api<{ id: number }>("/api/tickets", { method: "POST", json: { name: name || null, target: t.target, kind: "manual", legs: t.legs.map((l) => ({ match_id: l.match_id, key: l.key })) } });
      setSaved(`Saved as ticket #${r.id}. Track it on Historical performance.`);
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <div className="panel slip">
      <div className="panel-h"><h2>Your ticket</h2><span className="sub">{t.busy ? "checking…" : `${t.legs.length} selections`}</span></div>
      {t.legs.length === 0 ? <div className="empty small">Click a selection to add it. Combined odds update immediately.</div> : t.legs.map((l) => (
        <div className="slip-leg" key={l.match_id + l.key}>
          <div>
            <div style={{ fontWeight: 600 }}>{l.label}</div>
            <div className="muted tiny"><Link to={`/match/${enc(l.match_id)}`}>{l.match_label}</Link> · {l.kickoff_local ?? "TBC"}</div>
            <div className="row tiny" style={{ marginTop: 2, gap: 4 }}>
              <StatusChip value={l.tier} />
              <span className="muted">model {l.probability_pct}% · {l.odds_source === "manual" ? `${l.bookmaker} manual` : "snapshot price"}</span>
            </div>
          </div>
          <div className="stack" style={{ alignItems: "flex-end", gap: 4 }}>
            <span className="odds">{fmtOdds(l.odds)}</span>
            <button className="sm ghost danger" onClick={() => t.remove(l.match_id, l.key)} aria-label="Remove">✕</button>
          </div>
        </div>
      ))}
      <div className="slip-total">
        <div className="row between"><span className="muted small">Combined odds</span><span className="muted small">target {t.target}</span></div>
        <div className="big-odds">{fmtOdds(t.combined)}</div>
        <div className="progress" style={{ margin: "6px 0 8px" }}><i style={{ width: `${progress}%` }} /></div>
        {ev && (
          <div className="small stack" style={{ gap: 4 }}>
            <div className="row between"><span className="muted">Naive model estimate (all win)</span><b>{smallPct(ev.model_probability_all_win)}</b></div>
            <div className="row between"><span className="muted">Bookmaker implied</span><b>{smallPct(ev.bookmaker_implied_probability)}</b></div>
            {ev.weak_legs > 0 && <div className="notice warn small">{ev.weak_legs} weak selection(s) on this ticket.</div>}
            {ev.errors.length > 0 && <div className="notice bad small"><ul>{ev.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
            {ev.correlations.length > 0 && <div className="notice warn small"><b>Correlation</b><ul>{ev.correlations.map((c, i) => <li key={i}>{c.strength}: {c.note}</li>)}</ul></div>}
            {ev.warnings.length > 0 && <details><summary className="muted">{ev.warnings.length} warnings</summary><ul className="plain">{ev.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
          </div>
        )}
        <ErrorBox error={t.error ?? err} />
        <div className="row" style={{ marginTop: 8 }}>
          <input placeholder="Ticket name (optional)" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} />
        </div>
        <div className="row" style={{ marginTop: 6 }}>
          <button className="primary" disabled={!t.legs.length || busyReport} onClick={onReport}>{busyReport ? "Building…" : "Report for this ticket"}</button>
          <button disabled={!t.legs.length || !ev?.valid} onClick={save}>Save & track</button>
          <button className="ghost" disabled={!t.legs.length} onClick={t.clear}>Clear</button>
        </div>
        {saved && <div className="notice good small" style={{ marginTop: 6 }}>{saved}</div>}
      </div>
    </div>
  );
}

export default function Accumulator() {
  const t = useTicket();
  const [range, setRange] = usePersistent("acc.range", { from: todayLocal(), to: addDays(todayLocal(), 1) });
  const [comps, setComps] = usePersistent<string[]>("acc.comps", []);
  const [custom, setCustom] = useState("");
  const [useAi, setUseAi] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [onlyPriced, setOnlyPriced] = useState(true);
  const pool = useFetch<Summary[]>(`/api/window${qs({ date_from: range.from, date_to: range.to, competitions: comps.join(",") })}`);

  const run = async (manual: boolean) => {
    setBusy(true); setErr(null);
    try {
      const r = await api<Report>("/api/accumulator/report", { method: "POST", json: { date_from: range.from, date_to: range.to, target: t.target, competitions: comps.length ? comps : null, ai: useAi, legs: manual ? t.legs.map((l) => ({ match_id: l.match_id, key: l.key })) : null } });
      setReport(r);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const loadBuilt = async (legs: Report[]) => t.replace(legs.map((l) => ({ match_id: l.match_id, key: l.key })));

  const rows = (pool.data ?? []).filter((s) => s.status !== "rejected" && s.qualifying.length > 0 && (!onlyPriced || s.qualifying.some((q) => q.price)));
  rows.sort((a, b) => (b.recommendation?.score ?? 0) - (a.recommendation?.score ?? 0));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Accumulator builder</h1>
          <p>Combined odds = odds₁ × odds₂ × … The builder only uses selections that pass the evidence gates and stops at the target; it will not pad a ticket with weak legs. A smaller, better-supported ticket beats a padded one.</p>
        </div>
      </div>
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-b stack">
          <div className="row">
            <span className="muted small">Target odds</span>
            <div className="seg">{PRESETS.map((p) => <button key={p} className={t.target === p ? "on" : ""} onClick={() => t.setTarget(p)}>{p}</button>)}</div>
            <input type="number" min="1.1" step="1" placeholder="Custom" value={custom} onChange={(e) => setCustom(e.target.value)} style={{ width: 90 }} />
            <button className="sm" disabled={!(Number(custom) > 1)} onClick={() => t.setTarget(Number(custom))}>Set</button>
          </div>
          <div className="row">
            <DateRange from={range.from} to={range.to} onChange={(f, to) => setRange({ from: f, to })} />
            <CompetitionPicker value={comps} onChange={setComps} />
          </div>
          <div className="row">
            <button className="primary" onClick={() => run(false)} disabled={busy}>{busy ? "Analysing…" : `Auto-build toward ${t.target}`}</button>
            <label className="check"><input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} /> Add local AI summary (Ollama, if enabled)</label>
          </div>
        </div>
      </div>
      <ErrorBox error={err} />
      <div className="grid g-side">
        <div className="stack">
          {report && (
            <>
              <div className="row between">
                <h2>Report</h2>
                <div className="row">
                  {report.legs.length > 0 && report.mode === "auto" && <button onClick={() => loadBuilt(report.legs)}>Load main ticket into slip</button>}
                  {report.alternative_ticket && <button onClick={() => loadBuilt(report.alternative_ticket.legs)}>Load alternative</button>}
                  <button className="ghost" onClick={() => setReport(null)}>Close report</button>
                </div>
              </div>
              <ReportView r={report} />
            </>
          )}
          <Panel title="Selection pool" sub="best qualifying markets per match — click to add" tight
            actions={<label className="check"><input type="checkbox" checked={onlyPriced} onChange={(e) => setOnlyPriced(e.target.checked)} /> only priced</label>}>
            <ErrorBox error={pool.error} onRetry={pool.reload} />
            {pool.loading && !pool.data ? <Loading label="Analysing fixtures…" /> : rows.length === 0 ? (
              <Empty>No qualifying {onlyPriced ? "priced " : ""}selections in this window. {onlyPriced ? "Untick “only priced” to see markets that need Bet365 odds entered." : "Every fixture was rejected or lacks supporting data — see Rejected matches."}</Empty>
            ) : rows.map((s) => (
              <div className="pick-row" key={s.fixture.id}>
                <div style={{ minWidth: 0 }}>
                  <div className="row" style={{ gap: 6 }}>
                    <Link to={`/match/${enc(s.fixture.id)}`} className="teams">{s.fixture.home}<span className="v">v</span>{s.fixture.away}</Link>
                    <StatusChip value={s.status} />
                    <span className="muted tiny">{s.fixture.competition_name} · {s.fixture.kickoff_local ?? "TBC"} · DQ {Math.round(s.data_quality)}</span>
                  </div>
                  <div className="row" style={{ marginTop: 5, gap: 6 }}>
                    {s.qualifying.filter((q) => !onlyPriced || q.price).slice(0, 4).map((q) => {
                      const on = t.has(s.fixture.id, q.key);
                      return q.price ? (
                        <button key={q.key} className={`pick ${on ? "on" : ""}`} onClick={() => (on ? t.remove(s.fixture.id, q.key) : t.add(s.fixture.id, q.key))} title={`Model ${q.probability_pct}% (${q.range_pct?.join("–")}%) · score ${q.score} · ${q.tier} · ${q.price.source === "manual" ? "manual price" : "snapshot price"}`}>
                          {q.label} <Chip tone={q.tier === "strong" ? "good" : q.tier === "acceptable" ? "info" : "warn"}>{q.probability_pct}%</Chip>
                          <span className="o">{fmtOdds(q.price.odds)}</span>
                        </button>
                      ) : (
                        <Link key={q.key} to={`/match/${enc(s.fixture.id)}`} className="pick" title="Enter odds on the match page">{q.label} <Chip>{q.probability_pct}%</Chip><span className="o muted">odds?</span></Link>
                      );
                    })}
                  </div>
                </div>
                <div className="right small muted nowrap">{s.recommendation ? `score ${s.recommendation.score}` : ""}</div>
              </div>
            ))}
          </Panel>
        </div>
        <Slip onReport={() => run(true)} busyReport={busy} />
      </div>
    </div>
  );
}
