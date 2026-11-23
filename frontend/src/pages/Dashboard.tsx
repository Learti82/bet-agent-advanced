import { Link } from "react-router-dom";
import { enc, qs, type Summary } from "../api";
import { useStatus } from "../App";
import { Chip, Empty, ErrorBox, Loading, Panel, Stat, StatusChip, useFetch } from "../components/ui";
import { addDays, fmtOdds, pct, todayLocal } from "../format";
import { useTicket } from "../ticket";

export default function Dashboard() {
  const { status } = useStatus();
  const t = useTicket();
  const today = todayLocal();
  const win = useFetch<Summary[]>(`/api/window${qs({ date_from: today, date_to: addDays(today, 1) })}`);
  const perf = useFetch<{ overall: Record<string, number | null>; sample_note: string }>("/api/performance");
  const list = win.data ?? [];
  const counts = { candidate: 0, flagged: 0, rejected: 0, ineligible: 0 } as Record<string, number>;
  list.forEach((s) => (counts[s.status] = (counts[s.status] ?? 0) + 1));
  const best = list
    .filter((s) => s.recommendation && s.status !== "rejected")
    .sort((a, b) => (b.recommendation!.score) - (a.recommendation!.score))
    .slice(0, 12);
  const d = status?.dataset;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p>Today and tomorrow ({today} – {addDays(today, 1)}, Europe/Belgrade). Every number below comes from the local dataset, your manual entries, and deterministic calculations.</p>
        </div>
        <div className="row"><Link to="/plan"><button className="primary">This week's plan</button></Link><Link to="/accumulator"><button>Accumulator builder</button></Link></div>
      </div>
      {status?.warnings.map((w, i) => <div key={i} className="notice warn" style={{ marginBottom: 8 }}>{w} {!d && <Link to="/data">Go to Data sources →</Link>}</div>)}
      <div className="grid g4" style={{ marginBottom: 12 }}>
        <Stat k="Dataset" v={d ? (d.age_days != null ? `${d.age_days < 1 ? Math.round(d.age_days * 24) + " h" : d.age_days.toFixed(1) + " d"}` : "?") : "—"} d={d ? `built ${d.generated_utc ?? "unknown"} · ${d.competitions} competitions` : "not imported"} />
        <Stat k="Fixtures analysed" v={win.loading ? "…" : list.length} d={<span>{counts.candidate} candidates · {counts.flagged} flagged · {counts.rejected} rejected</span>} />
        <Stat k="Current ticket" v={fmtOdds(t.combined)} d={`${t.legs.length} legs · target ${t.target}`} meter={t.combined ? (Math.log(t.combined) / Math.log(t.target)) * 100 : 0} />
        <Stat k="Tracked selections" v={perf.data ? `${perf.data.overall.settled ?? 0}/${perf.data.overall.total ?? 0}` : "…"} d={perf.data ? `settled · hit rate ${pct(perf.data.overall.hit_rate as number | null)}` : ""} />
      </div>
      <div className="grid g-side">
        <Panel title="Best-supported selections" sub="highest selection scores, today & tomorrow" tight>
          <ErrorBox error={win.error} onRetry={win.reload} />
          {win.loading ? <Loading label="Analysing fixtures…" /> : best.length === 0 ? <Empty>No market passes the evidence gates in this window. That is a legitimate outcome.</Empty> : (
            <div className="tbl-wrap"><table className="tbl">
              <thead><tr><th>Kickoff</th><th>Match</th><th>Selection</th><th className="num">Model</th><th className="num">Price</th><th className="num">Score</th><th>Status</th></tr></thead>
              <tbody>{best.map((s) => {
                const r = s.recommendation!;
                return (
                  <tr key={s.fixture.id}>
                    <td className="num nowrap">{s.fixture.kickoff_local?.slice(5) ?? "TBC"}</td>
                    <td><Link to={`/match/${enc(s.fixture.id)}`} className="teams">{s.fixture.home}<span className="v">v</span>{s.fixture.away}</Link><div className="muted tiny">{s.fixture.competition_name}</div></td>
                    <td>{r.label}</td>
                    <td className="num">{r.probability_pct}% <span className="muted tiny">{r.range_pct?.join("–")}</span></td>
                    <td className="num">{r.price ? <>{fmtOdds(r.price.odds)} <span className="muted tiny">{r.price.source === "manual" ? "manual" : "snap"}</span></> : <span className="muted">enter</span>}</td>
                    <td className="num"><b>{r.score}</b></td>
                    <td><StatusChip value={s.status} /> <Chip tone={r.tier === "strong" ? "good" : r.tier === "acceptable" ? "info" : "warn"}>{r.tier}</Chip></td>
                  </tr>
                );
              })}</tbody>
            </table></div>
          )}
        </Panel>
        <div className="stack">
          <Panel title="Workflow">
            <ol style={{ margin: 0, paddingLeft: 18 }} className="small">
              <li><Link to="/data">Import</Link> the latest Open-Matchday data (daily).</li>
              <li>Browse <Link to="/fixtures">fixtures</Link>; verify kickoff times you plan to use.</li>
              <li>On each <Link to="/research">match page</Link>, enter your Bet365 prices and any research.</li>
              <li>Build the ticket in the <Link to="/accumulator">accumulator builder</Link>.</li>
              <li>Save it, and let imports settle it on <Link to="/performance">performance</Link>.</li>
            </ol>
          </Panel>
          <Panel title="Rejections" sub="today & tomorrow">
            {list.filter((s) => s.status === "rejected").slice(0, 6).map((s) => (
              <div key={s.fixture.id} className="small" style={{ marginBottom: 6 }}>
                <Link to={`/match/${enc(s.fixture.id)}`}>{s.fixture.home} v {s.fixture.away}</Link>
                <div className="muted">{s.reasons[0]}</div>
              </div>
            ))}
            <Link to="/rejected" className="small">All rejected matches →</Link>
          </Panel>
          {perf.data && <div className="notice small">{perf.data.sample_note}</div>}
        </div>
      </div>
    </div>
  );
}
