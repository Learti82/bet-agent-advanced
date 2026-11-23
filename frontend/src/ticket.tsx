import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type Leg, type TicketEvaluation } from "./api";
import { combinedOdds } from "./format";

// The working ticket lives in the browser (localStorage) so it survives reloads; the backend
// re-validates it (prices, kickoff, duplicates, correlations) on every change.

interface TicketCtx {
  legs: Leg[];
  target: number;
  setTarget: (t: number) => void;
  add: (matchId: string, key: string) => Promise<void>;
  remove: (matchId: string, key: string) => void;
  clear: () => void;
  replace: (legs: { match_id: string; key: string }[]) => Promise<void>;
  has: (matchId: string, key: string) => boolean;
  combined: number | null;
  evaluation: TicketEvaluation | null;
  error: string | null;
  busy: boolean;
}

const Ctx = createContext<TicketCtx | null>(null);
const STORE_KEY = "matchedge.ticket.v1";

function load(): { refs: { match_id: string; key: string }[]; target: number } {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* storage unavailable */
  }
  return { refs: [], target: 110 };
}

export function TicketProvider({ children }: { children: ReactNode }) {
  const initial = useRef(load());
  const [legs, setLegs] = useState<Leg[]>([]);
  const [target, setTarget] = useState<number>(initial.current.target);
  const [evaluation, setEvaluation] = useState<TicketEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const evaluate = useCallback(async (refs: { match_id: string; key: string }[], tgt: number) => {
    setBusy(true);
    try {
      const res = await api<{ legs: Leg[]; evaluation: TicketEvaluation }>("/api/accumulator/evaluate", {
        method: "POST",
        json: { legs: refs, target: tgt },
      });
      setLegs(res.legs);
      setEvaluation(res.evaluation);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (initial.current.refs.length) void evaluate(initial.current.refs, initial.current.target);
  }, [evaluate]);

  const refs = useMemo(() => legs.map((l) => ({ match_id: l.match_id, key: l.key })), [legs]);

  useEffect(() => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ refs, target }));
    } catch {
      /* ignore */
    }
  }, [refs, target]);

  const value: TicketCtx = {
    legs,
    target,
    setTarget: (t) => {
      setTarget(t);
      void evaluate(refs, t);
    },
    add: async (matchId, key) => {
      if (refs.some((r) => r.match_id === matchId && r.key === key)) return;
      await evaluate([...refs, { match_id: matchId, key }], target);
    },
    remove: (matchId, key) => {
      const next = refs.filter((r) => !(r.match_id === matchId && r.key === key));
      setLegs((ls) => ls.filter((l) => !(l.match_id === matchId && l.key === key)));
      void evaluate(next, target);
    },
    clear: () => {
      setLegs([]);
      setEvaluation(null);
    },
    replace: async (next) => evaluate(next, target),
    has: (matchId, key) => refs.some((r) => r.match_id === matchId && r.key === key),
    combined: legs.length ? combinedOdds(legs.map((l) => l.odds)) : null,
    evaluation,
    error,
    busy,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTicket(): TicketCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTicket outside provider");
  return v;
}
