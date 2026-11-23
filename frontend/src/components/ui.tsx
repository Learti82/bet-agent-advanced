import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { STATUS_TONE, addDays, todayLocal, weekday } from "../format";

export function useFetch<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const seq = useRef(0);
  const reload = useCallback(async () => {
    if (!path) return;
    const my = ++seq.current;
    setLoading(true);
    try {
      const d = await api<T>(path);
      if (my === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (my === seq.current) setError((e as Error).message);
    } finally {
      if (my === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

export function Panel({ title, sub, actions, children, tight, className }: {
  title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; tight?: boolean; className?: string;
}) {
  return (
    <section className={`panel ${className ?? ""}`}>
      {(title || actions) && (
        <div className="panel-h">
          <div className="row">
            {title && <h2>{title}</h2>}
            {sub && <span className="sub">{sub}</span>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      <div className={`panel-b ${tight ? "tight" : ""}`}>{children}</div>
    </section>
  );
}

export function Chip({ tone, children, title }: { tone?: string; children: ReactNode; title?: string }) {
  return <span className={`chip ${tone ?? ""}`} title={title}>{children}</span>;
}

export function StatusChip({ value }: { value: string }) {
  return <Chip tone={STATUS_TONE[value] ?? ""}>{value.replace("_", " ")}</Chip>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="loading"><span className="spinner" />{label}</div>;
}

export function ErrorBox({ error, onRetry }: { error: string | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="notice bad row between">
      <span>{error}</span>
      {onRetry && <button className="sm" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function FormSeq({ seq }: { seq: string }) {
  if (!seq) return <span className="muted">—</span>;
  return <span className="formseq" title="Most recent first">{seq.split("").map((c, i) => <i key={i} className={c}>{c}</i>)}</span>;
}

export function Stat({ k, v, d, meter }: { k: string; v: ReactNode; d?: ReactNode; meter?: number }) {
  return (
    <div className="panel stat">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {d && <div className="d">{d}</div>}
      {meter != null && <div className="meter"><i style={{ width: `${Math.max(0, Math.min(100, meter))}%` }} /></div>}
    </div>
  );
}

export function DateRange({ from, to, onChange }: { from: string; to: string; onChange: (f: string, t: string) => void }) {
  const today = todayLocal();
  const span = Math.round((Date.parse(to) - Date.parse(from)) / 86400000);
  return (
    <div className="row">
      <button className="sm" onClick={() => onChange(addDays(from, -1), addDays(to, -1))} aria-label="Previous day">‹</button>
      <input type="date" value={from} onChange={(e) => e.target.value && onChange(e.target.value, e.target.value > to ? e.target.value : to)} />
      <span className="muted">to</span>
      <input type="date" value={to} min={from} onChange={(e) => e.target.value && onChange(from, e.target.value)} />
      <button className="sm" onClick={() => onChange(addDays(from, 1), addDays(to, 1))} aria-label="Next day">›</button>
      <div className="seg">
        <button className={from === today && span === 0 ? "on" : ""} onClick={() => onChange(today, today)}>Today</button>
        <button className={from === addDays(today, 1) && span === 0 ? "on" : ""} onClick={() => onChange(addDays(today, 1), addDays(today, 1))}>Tomorrow</button>
        <button className={from === today && span === 2 ? "on" : ""} onClick={() => onChange(today, addDays(today, 2))}>3 days</button>
        <button className={from === today && span === 6 ? "on" : ""} onClick={() => onChange(today, addDays(today, 6))}>7 days</button>
      </div>
      <span className="muted small">{from === to ? weekday(from) : `${weekday(from)} – ${weekday(to)}`} · Europe/Belgrade</span>
    </div>
  );
}

export interface Competition { code: string; name: string; country: string; kind: string; n_fixtures: number; n_results: number; coverage: Record<string, number>; has_odds: number; latest_result: string | null }

export const MAJOR = [
  "ENG_1_premier-league", "ESP_1_la-liga", "GER_1_bundesliga", "ITA_1_serie-a", "FRA_1_ligue-1",
  "UEFA_1_champions-league", "UEFA_1_europa-league", "UEFA_1_conference-league", "NED_1_eredivisie", "POR_1_primeira-liga",
];

export function CompetitionPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const { data } = useFetch<Competition[]>("/api/competitions");
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const comps = (data ?? []).filter((c) => !q || `${c.name} ${c.country}`.toLowerCase().includes(q.toLowerCase()));
  const toggle = (code: string) => onChange(value.includes(code) ? value.filter((v) => v !== code) : [...value, code]);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button onClick={() => setOpen((o) => !o)}>
        Competitions: {value.length ? `${value.length} selected` : "all"} ▾
      </button>
      {open && (
        <div className="panel" style={{ position: "absolute", zIndex: 20, top: "110%", left: 0, width: 330, maxHeight: 420, overflow: "auto", padding: 8 }}>
          <div className="row" style={{ marginBottom: 6 }}>
            <input placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} autoFocus />
            <button className="sm" onClick={() => onChange(MAJOR.filter((m) => (data ?? []).some((c) => c.code === m)))}>Major</button>
            <button className="sm ghost" onClick={() => onChange([])}>All</button>
          </div>
          {comps.map((c) => (
            <label key={c.code} className="check" style={{ display: "flex", padding: "3px 2px" }}>
              <input type="checkbox" checked={value.includes(c.code)} onChange={() => toggle(c.code)} />
              <span style={{ flex: 1 }}>{c.name} <span className="muted tiny">{c.country}</span></span>
              <span className="muted tiny num">{c.n_fixtures}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function usePersistent<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = (nv: T) => {
    setV(nv);
    try { localStorage.setItem(key, JSON.stringify(nv)); } catch { /* ignore */ }
  };
  return [v, set];
}
