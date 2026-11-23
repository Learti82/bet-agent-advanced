import { createContext, useContext } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import type { Status } from "./api";
import { useFetch } from "./components/ui";
import { fmtOdds } from "./format";
import { useTicket } from "./ticket";
import Dashboard from "./pages/Dashboard";
import WeeklyPlan from "./pages/WeeklyPlan";
import Fixtures from "./pages/Fixtures";
import MatchResearch from "./pages/MatchResearch";
import Accumulator from "./pages/Accumulator";
import Rejected from "./pages/Rejected";
import Performance from "./pages/Performance";
import DataSources from "./pages/DataSources";
import Settings from "./pages/Settings";

interface StatusCtxT { status: Status | null; reloadStatus: () => void }
const StatusCtx = createContext<StatusCtxT>({ status: null, reloadStatus: () => {} });
export const useStatus = () => useContext(StatusCtx);

const NAV = [
  ["/", "Dashboard"],
  ["/plan", "Weekly plan"],
  ["/fixtures", "Upcoming fixtures"],
  ["/research", "Match research"],
  ["/accumulator", "Accumulator builder"],
  ["/rejected", "Rejected matches"],
  ["/performance", "Historical performance"],
  ["/data", "Data sources"],
  ["/settings", "Settings"],
] as const;

function Freshness({ status }: { status: Status | null }) {
  if (!status) return null;
  const d = status.dataset;
  if (!d) return <Link to="/data" className="chip bad">No dataset imported</Link>;
  const age = d.age_days;
  const tone = age == null ? "warn" : age <= 1 ? "good" : age <= 3 ? "warn" : "bad";
  const label = age == null ? "build time unknown" : age < 1 ? `${Math.round(age * 24)} h old` : `${age.toFixed(1)} days old`;
  return (
    <Link to="/data" className={`chip ${tone}`} title={`Open-Matchday build ${d.generated_utc ?? "unknown"}`}>
      <span className="dot" /> Data {label}
    </Link>
  );
}

export default function App() {
  const { data: status, reload } = useFetch<Status>("/api/status");
  const ticket = useTicket();
  return (
    <StatusCtx.Provider value={{ status, reloadStatus: reload }}>
      <div className="shell">
        <aside className="side">
          <div className="brand">
            <div className="brand-mark">
              <svg width="16" height="16" viewBox="0 0 32 32" aria-hidden><path d="M5 24 L13 12 L19 19 L27 7" stroke="#fff" strokeWidth="3.5" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <div>
              <div className="brand-name">MatchEdge</div>
              <div className="brand-sub">Local research agent</div>
            </div>
          </div>
          <nav className="nav">
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"}>
                <span>{label}</span>
                {to === "/accumulator" && ticket.legs.length > 0 && <span className="count">{ticket.legs.length}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="side-foot">
            Runs on this computer. No paid APIs, no cloud AI.
            <br />Data: <a href="https://github.com/oladeeayo/open-matchday" target="_blank" rel="noreferrer">open-matchday</a> (non-commercial).
          </div>
        </aside>
        <div className="main">
          <header className="topbar">
            <Freshness status={status} />
            {status && <span className="chip outline">{status.now_local} {status.timezone}</span>}
            {status && <span className="chip outline">Prices: {status.bookmaker} · manual entry</span>}
            <span className="chip outline" title="Optional local model via Ollama">AI: {status?.ai.enabled ? status.ai.model : "off (deterministic)"}</span>
            <div className="spacer" />
            <Link to="/accumulator" className="ticket-chip" title="Current ticket">
              Ticket · {ticket.legs.length} {ticket.legs.length === 1 ? "leg" : "legs"} <b>{fmtOdds(ticket.combined)}</b>
              <span style={{ opacity: 0.6 }}>/ {ticket.target}</span>
            </Link>
          </header>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/plan" element={<WeeklyPlan />} />
            <Route path="/fixtures" element={<Fixtures />} />
            <Route path="/research" element={<MatchResearch />} />
            <Route path="/match/:id" element={<MatchResearch />} />
            <Route path="/accumulator" element={<Accumulator />} />
            <Route path="/rejected" element={<Rejected />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/data" element={<DataSources />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<div className="page"><h1>Not found</h1></div>} />
          </Routes>
        </div>
      </div>
    </StatusCtx.Provider>
  );
}
