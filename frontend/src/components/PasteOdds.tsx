import { useState } from "react";
import { api } from "../api";
import { nowLocalInput } from "../format";
import { ErrorBox } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Row = { match_id: string; match_label: string; market: string; selection: string; line: number | null; odds: number; raw: string; keep: boolean };

const MARKET_LABEL: Record<string, string> = {
  "1X2": "Result", DC: "Double chance", DNB: "Draw no bet", BTTS: "BTTS", OU: "Goals", AH: "Asian hcp",
  "1H_OU": "1st-half goals", CORNERS_OU: "Corners", CARDS_OU: "Cards", TG_HOME: "Home goals", TG_AWAY: "Away goals",
};

export default function PasteOdds({ matchId, dateFrom, dateTo, onSaved }: { matchId?: string; dateFrom?: string; dateTo?: string; onSaved?: () => void }) {
  const [text, setText] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [ignored, setIgnored] = useState<any[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [bookmaker, setBookmaker] = useState("Bet365");
  const [checked, setChecked] = useState(nowLocalInput());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const parse = async () => {
    setErr(null); setMsg(null); setBusy(true);
    try {
      const r = await api<any>("/api/odds/parse", { method: "POST", json: { text, match_id: matchId, date_from: dateFrom, date_to: dateTo } });
      setRows(r.rows.map((x: any) => ({ ...x, keep: true })));
      setIgnored(r.ignored); setWarnings(r.warnings);
      setChecked(nowLocalInput());
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const save = async () => {
    if (!rows) return;
    setErr(null); setBusy(true);
    try {
      const keep = rows.filter((r) => r.keep);
      const r = await api<any>("/api/odds/bulk", { method: "POST", json: { rows: keep, bookmaker, checked_at: checked } });
      setMsg(`Saved ${r.saved} price${r.saved === 1 ? "" : "s"} as manual entries.${r.errors.length ? ` ${r.errors.length} rejected: ${r.errors.join("; ")}` : ""}`);
      if (r.saved) { setRows(null); setText(""); onSaved?.(); }
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const set = (i: number, patch: Partial<Row>) => setRows((rs) => rs!.map((r, k) => (k === i ? { ...r, ...patch } : r)));

  return (
    <div className="stack" style={{ gap: 8 }}>
      <p className="small muted">
        On the Bet365 page select a market (its heading, selections and prices) or a whole coupon, copy, and paste it here.
        {matchId ? "" : " Include the match line (e.g. “Arsenal v Dortmund”) or copy a coupon list with both team names."} Nothing is saved until you confirm the preview.
      </p>
      <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={"Arsenal v Dortmund\nFull Time Result\nArsenal 1.65\nDraw 4.00\nDortmund 5.00\nGoals Over/Under\nOver 2.5 1.80\nUnder 2.5 2.00"} style={{ minHeight: 140, fontFamily: "var(--mono)", fontSize: 12 }} />
      <div className="row"><button className="primary" onClick={parse} disabled={!text.trim() || busy}>{busy ? "Reading…" : "Read prices"}</button>{rows && <button className="ghost" onClick={() => setRows(null)}>Discard</button>}</div>
      <ErrorBox error={err} />
      {msg && <div className="notice good small">{msg}</div>}
      {rows && (
        <div className="panel" style={{ padding: 10 }}>
          <div className="row" style={{ marginBottom: 8 }}>
            <b>{rows.length} prices recognised</b>
            <span className="muted small">Untick anything wrong; you can correct a price before saving.</span>
          </div>
          {rows.length > 0 && (
            <div className="tbl-wrap" style={{ maxHeight: 360 }}>
              <table className="tbl">
                <thead><tr><th></th><th>Match</th><th>Market</th><th>Selection</th><th className="num">Line</th><th className="num">Odds</th><th>From text</th></tr></thead>
                <tbody>{rows.map((r, i) => (
                  <tr key={i} className={r.keep ? "" : "dim"}>
                    <td><input type="checkbox" checked={r.keep} onChange={(e) => set(i, { keep: e.target.checked })} /></td>
                    <td className="small">{r.match_label}</td>
                    <td>{MARKET_LABEL[r.market] ?? r.market}</td>
                    <td>{r.selection}</td>
                    <td className="num">{r.line ?? ""}</td>
                    <td className="num"><input type="number" step="0.01" value={r.odds} onChange={(e) => set(i, { odds: Number(e.target.value) })} style={{ width: 76 }} /></td>
                    <td className="mono muted">{r.raw}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {warnings.length > 0 && <div className="notice warn small" style={{ marginTop: 8 }}>{warnings.map((w, i) => <div key={i}>{w}</div>)}</div>}
          {ignored.length > 0 && <details style={{ marginTop: 8 }}><summary className="small muted">{ignored.length} lines not used</summary><ul className="plain small">{ignored.map((x, i) => <li key={i}><span className="mono">{x.text}</span> — {x.reason}</li>)}</ul></details>}
          <div className="row" style={{ marginTop: 10 }}>
            <label className="f">Bookmaker<input value={bookmaker} onChange={(e) => setBookmaker(e.target.value)} /></label>
            <label className="f">Checked at (Belgrade)<input value={checked} onChange={(e) => setChecked(e.target.value)} /></label>
            <button className="primary" style={{ alignSelf: "flex-end" }} disabled={busy || !rows.some((r) => r.keep)} onClick={save}>Save {rows.filter((r) => r.keep).length} prices</button>
          </div>
        </div>
      )}
    </div>
  );
}
