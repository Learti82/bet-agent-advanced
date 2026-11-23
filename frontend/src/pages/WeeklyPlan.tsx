import { useState } from "react";
import { Link } from "react-router-dom";
import { api, enc, qs, type Report } from "../api";
import PasteOdds from "../components/PasteOdds";
import ReportView from "../components/Report";
import { Chip, CompetitionPicker, ErrorBox, Loading, Panel, StatusChip, useFetch } from "../components/ui";
import { addDays, fmtOdds, smallPct, todayLocal } from "../format";
import { useTicket } from "../ticket";

/* eslint-disable @typescript-eslint/no-explicit-any */
type G = Record<string, any>;

function monday(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  const wd = (d.getUTCDay() + 6) % 7;
  return addDays(iso, -wd);
}

function dayName(iso: string) {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

function TicketCard({ slot, t, weekStart }: { slot: G; t: G; weekStart: string }) {
  const ticket = useTicket();
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const r: Report = t.report;
  const ev = r.evaluation;
  const legs: G[] = r.legs;
  const reached = ev.target_reached;
  const refs = legs.map((l) => ({ match_id: l.match_id, key: l.key }));
  const save = async () => {
    setErr(null); setSaved(null);
    try {
      const res = await api<{ id: number }>("/api/tickets", { method: "POST", json: { name: `${slot.name} · target ${t.target} · week ${weekStart}`, target: t.target, kind: "main", legs: refs } });
      setSaved(`Saved as ticket #${res.id}`);
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <div className="panel" style={{ display: "flex", flexDirection: "column" }}>
      <div className="panel-h">
        <div className="row"><h3>Target {t.target}</h3>{legs.length > 0 && (reached ? <Chip tone="good">reached</Chip> : <Chip tone="warn">below target — not padded</Chip>)}</div>
        <span className="sub">{legs.length} legs</span>
      </div>
      <div className="panel-b" style={{ flex: 1 }}>
        {legs.length === 0 ? <p className="muted small">{r.final_opinion}</p> : (
          <>
            <div className="row" style={{ alignItems: "baseline", gap: 14, marginBottom: 6 }}>
              <span className="big-odds" style={{ color: reached ? "var(--good)" : "var(--warn)" }}>{fmtOdds(ev.combined_odds)}</span>
              <span className="small muted">model estimate all win <b>{smallPct(ev.model_probability_all_win)}</b> · price implies <b>{smallPct(ev.bookmaker_implied_probability)}</b></span>
            </div>
            <table className="tbl">
              <tbody>{legs.map((l) => (
                <tr key={l.match_id + l.key}>
                  <td><Link to={`/match/${enc(l.match_id)}`}>{l.match_label}</Link><div className="muted tiny">{l.competition_name} · {l.kickoff_local ?? "TBC"}</div></td>
                  <td>{l.label}<div className="tiny"><StatusChip value={l.tier} /> <span className="muted">model {l.probability_pct}%</span></div></td>
                  <td className="num"><b>{fmtOdds(l.odds)}</b><div className="tiny muted">{l.odds_source === "manual" ? `${l.bookmaker} manual` : "snapshot"}</div></td>
                </tr>
              ))}</tbody>
            </table>
            <p className="small" style={{ marginTop: 8 }}>{r.final_opinion}</p>
          </>
        )}
        <ErrorBox error={err} />
        {saved && <div className="notice good small">{saved} — track it on <Link to="/performance">Historical performance</Link>.</div>}
      </div>
      {legs.length > 0 && (
        <div className="row" style={{ padding: "10px 14px", borderTop: "1px solid var(--line)" }}>
          <button className="primary" onClick={() => ticket.replace(refs)}>Load into slip</button>
          <button onClick={save} disabled={!ev.valid}>Save & track</button>
          <button className="ghost" onClick={() => setOpen((o) => !o)}>{open ? "Hide full report" : "Full report"}</button>
        </div>
      )}
      {open && <div style={{ padding: 12, borderTop: "1px solid var(--line)" }}><ReportView r={r} /></div>}
    </div>
  );
}

function Slot({ slot, weekStart }: { slot: G; weekStart: string }) {
  const tone = slot.status === "ok" ? "" : slot.status === "passed" ? "muted" : "warn";
  return (
    <Panel
      title={<>{slot.name} <span className="muted" style={{ fontWeight: 400 }}>· {slot.days_label}</span></>}
      sub={slot.dates.map(dayName).join(" & ")}
      actions={<span className="muted small">{slot.fixtures} fixtures · {slot.eligible_fixtures} pre-match · {slot.priced_fixtures} priced ({slot.manual_priced_fixtures} by you)</span>}>
      <div className="muted tiny" style={{ marginBottom: 8 }}>{slot.competition_names.join(", ")}</div>
      {slot.status !== "ok" ? <div className={`notice ${tone}`}>{slot.message}</div> : (
        <>
          {slot.shared_legs > 0 && <div className="notice info small" style={{ marginBottom: 10 }}>{slot.shared_legs} legs appear on both tickets: if one of them loses, both tickets lose.</div>}
          {slot.priced_fixtures < slot.eligible_fixtures && <div className="small muted" style={{ marginBottom: 8 }}>{slot.eligible_fixtures - slot.priced_fixtures} fixtures have no price yet — enter Bet365 odds on their match pages to make them available.</div>}
          <div className="grid g2">{slot.tickets.map((t: G, i: number) => {
            const sig = (x: G) => x.report.legs.map((l: G) => l.match_id + l.key).sort().join("|");
            const prev = i > 0 ? slot.tickets[i - 1] : null;
            if (prev && t.report.legs.length > 0 && sig(prev) === sig(t)) {
              return (
                <div key={t.target} className="panel">
                  <div className="panel-h"><h3>Target {t.target}</h3><Chip tone="warn">same as target {prev.target}</Chip></div>
                  <div className="panel-b small">
                    <p>There are not enough well-supported, priced selections to build a bigger ticket than the {fmtOdds(t.report.evaluation.combined_odds)} one for target {prev.target}, so this slot has one honest ticket.</p>
                    <p className="muted">To go higher, enter your own Bet365 prices for qualifying markets on the match pages and press Rebuild — or accept that this slot does not support a {t.target} ticket this week.</p>
                  </div>
                </div>
              );
            }
            return <TicketCard key={t.target} slot={slot} t={t} weekStart={weekStart} />;
          })}</div>
        </>
      )}
    </Panel>
  );
}

export default function WeeklyPlan() {
  const [week, setWeek] = useState(monday(todayLocal()));
  const settings = useFetch<G>("/api/settings");
  const [targetsText, setTargetsText] = useState<string | null>(null);
  const targets = targetsText ?? settings.data?.values.plan_targets ?? "50,110";
  const plan = useFetch<G>(`/api/plan${qs({ week_start: week, targets })}`, [week, targets]);
  const weekendComps = useFetch<string[]>("/api/plan/weekend-competitions");
  const [msg, setMsg] = useState<string | null>(null);
  const saveTargets = async (value: string) => {
    try { await api("/api/settings", { method: "PUT", json: { plan_targets: value } }); setTargetsText(null); settings.reload(); setMsg(null); }
    catch (e) { setMsg((e as Error).message); }
  };
  const saveWeekend = async (codes: string[]) => {
    await api("/api/settings", { method: "PUT", json: { plan_weekend_competitions: codes } });
    weekendComps.reload();
    setMsg(null);
  };
  const thisWeek = monday(todayLocal());
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Weekly plan</h1>
          <p>Three separate ticket slots every week — Champions League on Tuesday & Wednesday, Europa + Conference League on Thursday, and league games on Saturday & Sunday — each built for every target. Only well-supported selections are used and no ticket is padded to reach its target.</p>
        </div>
      </div>
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-b row">
          <button className="sm" onClick={() => setWeek(addDays(week, -7))}>‹ Previous</button>
          <b className="num">{dayName(week)} – {dayName(addDays(week, 6))}</b>
          <button className="sm" onClick={() => setWeek(addDays(week, 7))}>Next ›</button>
          {week !== thisWeek && <button className="sm ghost" onClick={() => setWeek(thisWeek)}>This week</button>}
          <span className="muted small" style={{ marginLeft: 12 }}>Targets</span>
          <input value={targets} onChange={(e) => setTargetsText(e.target.value)} style={{ width: 110 }} />
          <button className="sm" onClick={() => saveTargets(targets)} disabled={targetsText == null}>Save as default</button>
          <span className="muted small" style={{ marginLeft: 12 }}>Weekend leagues</span>
          <CompetitionPicker value={weekendComps.data ?? []} onChange={saveWeekend} />
          <button className="sm ghost" onClick={() => saveWeekend([])} title="European top divisions">Reset</button>
          <button className="sm primary" onClick={plan.reload}>Rebuild</button>
        </div>
      </div>
      <ErrorBox error={msg ?? plan.error} onRetry={plan.reload} />
      {plan.loading && !plan.data ? <Loading label="Analysing every fixture in the week and building the tickets…" /> : plan.data && (
        <div className="stack">
          {plan.loading && <Loading label="Rebuilding…" />}
          <details className="panel" style={{ padding: 12 }}>
            <summary style={{ cursor: "pointer", fontWeight: 650 }}>Paste Bet365 odds for this week</summary>
            <div style={{ marginTop: 8 }}><PasteOdds dateFrom={week} dateTo={addDays(week, 6)} onSaved={plan.reload} /></div>
          </details>
          <div className="notice small">{plan.data.note} Prices marked “snapshot” are dataset quotes, not live Bet365 prices — re-check them, or enter your own on the match page and press Rebuild.</div>
          {plan.data.slots.map((s: G) => <Slot key={s.id} slot={s} weekStart={plan.data!.week_start} />)}
        </div>
      )}
    </div>
  );
}
