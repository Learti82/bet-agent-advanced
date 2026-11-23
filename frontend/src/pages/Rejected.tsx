import { useState } from "react";
import { Link } from "react-router-dom";
import { enc, qs, type Summary } from "../api";
import { Chip, CompetitionPicker, DateRange, Empty, ErrorBox, Loading, StatusChip, useFetch, usePersistent } from "../components/ui";
import { todayLocal } from "../format";

export default function Rejected() {
  const [range, setRange] = usePersistent("rej.range", { from: todayLocal(), to: todayLocal() });
  const [comps, setComps] = usePersistent<string[]>("rej.comps", []);
  const [show, setShow] = useState<"rejected" | "flagged" | "both">("rejected");
  const { data, loading, error, reload } = useFetch<Summary[]>(`/api/window${qs({ date_from: range.from, date_to: range.to, competitions: comps.join(",") })}`);
  const list = (data ?? []).filter((s) => (show === "both" ? s.status === "rejected" || s.status === "flagged" : s.status === show));
  const codes = new Map<string, number>();
  (data ?? []).filter((s) => s.status === "rejected").forEach((s) => s.factors.filter((f) => f.action === "reject").forEach((f) => codes.set(f.code, (codes.get(f.code) ?? 0) + 1)));
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Rejected matches</h1>
          <p>Not every fixture is a betting opportunity. These matches were analysed and rejected (or flagged) by explicit rules: small samples, closely matched teams, erratic form, conflicting evidence, lineup uncertainty you recorded, outdated data, or no market passing the gates.</p>
        </div>
      </div>
      <div className="panel" style={{ marginBottom: 12 }}><div className="panel-b row">
        <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f, to: t })} />
        <CompetitionPicker value={comps} onChange={setComps} />
        <div className="seg">{(["rejected", "flagged", "both"] as const).map((x) => <button key={x} className={show === x ? "on" : ""} onClick={() => setShow(x)}>{x}</button>)}</div>
      </div></div>
      {codes.size > 0 && <div className="row" style={{ marginBottom: 10 }}>{[...codes.entries()].sort((a, b) => b[1] - a[1]).map(([c, n]) => <Chip key={c} tone="outline">{c.replace(/_/g, " ")} · {n}</Chip>)}</div>}
      <ErrorBox error={error} onRetry={reload} />
      {loading ? <Loading label="Analysing fixtures…" /> : list.length === 0 ? <div className="panel"><Empty>No {show} matches in this range.</Empty></div> : (
        <div className="stack">
          {list.map((s) => (
            <div className="panel" key={s.fixture.id}>
              <div className="panel-h">
                <div className="row"><Link to={`/match/${enc(s.fixture.id)}`} className="teams">{s.fixture.home}<span className="v">v</span>{s.fixture.away}</Link><StatusChip value={s.status} /><span className="muted small">{s.fixture.competition_name} · {s.fixture.kickoff_local ?? "TBC"}</span></div>
                <span className="muted small">research {Math.round(s.research_score)} · data quality {Math.round(s.data_quality)} · risk {s.risk_level}</span>
              </div>
              <div className="panel-b grid g3 small">
                <div><b>Why</b><ul className="plain">{s.factors.filter((f) => f.action !== "info").map((f, i) => <li key={i}><Chip tone={f.severity === "high" ? "bad" : f.severity === "medium" ? "warn" : ""}>{f.severity}</Chip> {f.message}</li>)}</ul></div>
                <div><b>Missing information</b><ul className="plain">{s.missing_information.map((m, i) => <li key={i}>{m}</li>)}</ul></div>
                <div><b>Could another market be considered?</b>
                  {s.qualifying.length ? <ul className="plain">{s.qualifying.slice(0, 4).map((q) => <li key={q.key}>{q.label} — model {q.probability_pct}%, score {q.score}{s.status === "rejected" ? " (match-level rejection still applies)" : ""}</li>)}</ul> : <p className="muted">No market passes the evidence, probability and price gates.</p>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
