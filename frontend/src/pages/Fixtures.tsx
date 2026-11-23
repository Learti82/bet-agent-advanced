import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { qs, type Fixture, type Summary } from "../api";
import { Chip, CompetitionPicker, DateRange, Empty, ErrorBox, Loading, StatusChip, useFetch, usePersistent } from "../components/ui";
import { TIME_LABEL, todayLocal } from "../format";

export default function Fixtures() {
  const nav = useNavigate();
  const [range, setRange] = usePersistent("fx.range", { from: todayLocal(), to: todayLocal() });
  const [comps, setComps] = usePersistent<string[]>("fx.comps", []);
  const [team, setTeam] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [withAnalysis, setWithAnalysis] = usePersistent("fx.analysis", false);
  const from = range.from;
  const fx = useFetch<Fixture[]>(`/api/fixtures${qs({ date_from: from, date_to: range.to, competitions: comps.join(","), team, include_ineligible: true })}`);
  const win = useFetch<Summary[]>(withAnalysis ? `/api/window${qs({ date_from: from, date_to: range.to, competitions: comps.join(","), eligible_only: false })}` : null);
  const byId = useMemo(() => new Map((win.data ?? []).map((s) => [s.fixture.id, s])), [win.data]);
  const rows = (fx.data ?? []).filter((f) => showAll || f.prematch_eligible);
  const hidden = (fx.data ?? []).length - rows.length;
  const groups = useMemo(() => {
    const g = new Map<string, Fixture[]>();
    rows.forEach((f) => g.set(f.local_date, [...(g.get(f.local_date) ?? []), f]));
    return [...g.entries()];
  }, [rows]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Upcoming fixtures</h1>
          <p>From Open-Matchday fixture files. Kickoff times are converted to Europe/Belgrade; the dataset uses a fixed UTC+1 convention, so times are labelled by how far they can be trusted. A fixture stays <b>unverified</b> until you check it against the official competition website.</p>
        </div>
      </div>
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-b row">
          <DateRange from={range.from} to={range.to} onChange={(f, t) => setRange({ from: f, to: t })} />
          <CompetitionPicker value={comps} onChange={setComps} />
          <input placeholder="Team…" value={team} onChange={(e) => setTeam(e.target.value)} style={{ width: 150 }} />
          <label className="check"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show started / completed / postponed</label>
          <label className="check"><input type="checkbox" checked={withAnalysis} onChange={(e) => setWithAnalysis(e.target.checked)} /> Run analysis</label>
        </div>
      </div>
      <ErrorBox error={fx.error} onRetry={fx.reload} />
      {fx.loading && !fx.data ? <Loading /> : rows.length === 0 ? (
        <div className="panel"><Empty>No pre-match fixtures in this range{hidden ? ` (${hidden} started/completed hidden)` : ""}. The dataset only lists fixtures its sources have published.</Empty></div>
      ) : (
        <div className="stack">
          {withAnalysis && win.loading && <Loading label="Analysing fixtures (deterministic engine)…" />}
          {groups.map(([day, list]) => (
            <div className="panel" key={day}>
              <div className="panel-h"><h2>{new Date(`${day}T12:00:00Z`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}</h2><span className="sub">{list.length} fixtures</span></div>
              <div className="tbl-wrap">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Kickoff</th><th>Competition</th><th>Match</th><th>Status</th><th>Fixture</th>
                      {withAnalysis && <><th>Analysis</th><th>Most defensible market</th><th className="num">Model</th><th className="num">DQ</th></>}
                      <th className="num">Odds</th><th className="num">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((f) => {
                      const s = byId.get(f.id);
                      return (
                        <tr key={f.id} className={`click ${f.prematch_eligible ? "" : "dim"}`} onClick={() => nav(`/match/${encodeURIComponent(f.id)}`)}>
                          <td className="num nowrap">{f.kickoff_local ? f.kickoff_local.slice(11) : <span className="muted">TBC</span>}</td>
                          <td className="nowrap">{f.competition_name}</td>
                          <td className="teams">{f.home}<span className="v">v</span>{f.away}{f.score && <span className="muted"> ({f.score})</span>}</td>
                          <td>{f.prematch_eligible ? <Chip tone="info">{f.prematch_status}</Chip> : <Chip tone="muted">{f.prematch_status}</Chip>}</td>
                          <td className="nowrap">
                            {f.verified ? <Chip tone="good">verified</Chip> : <Chip tone="outline">unverified</Chip>}{" "}
                            <Chip tone={["corroborated", "user_corrected"].includes(f.time_certainty) ? "good" : f.time_certainty === "single_source" ? "" : "warn"} title={f.time_notes.join(" ")}>{TIME_LABEL[f.time_certainty] ?? f.time_certainty}</Chip>
                          </td>
                          {withAnalysis && (
                            <>
                              <td>{s ? <StatusChip value={s.status} /> : "…"}</td>
                              <td>{s?.recommendation ? s.recommendation.label : <span className="muted small">{s ? (s.reasons[0] ?? "—") : ""}</span>}</td>
                              <td className="num">{s?.recommendation?.probability_pct != null ? `${s.recommendation.probability_pct}%` : "—"}</td>
                              <td className="num">{s ? Math.round(s.data_quality) : ""}</td>
                            </>
                          )}
                          <td className="num nowrap">{f.manual_odds ? <Chip tone="good">{f.manual_odds} manual</Chip> : f.snapshot_odds ? <span className="muted small">snapshot</span> : <span className="muted">—</span>}</td>
                          <td className="num">{f.research_count ? <Chip tone="info">{f.research_count}</Chip> : ""}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
          {hidden > 0 && !showAll && <div className="muted small">{hidden} started, completed, postponed or unconfirmed fixtures hidden.</div>}
        </div>
      )}
    </div>
  );
}
