import { useState } from "react";
import { api } from "../api";
import { useStatus } from "../App";
import { Chip, Empty, ErrorBox, Loading, Panel, useFetch, type Competition } from "../components/ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
type G = Record<string, any>;

function cov(x: number | undefined) {
  if (x == null || x === 0) return <span className="muted">—</span>;
  const v = Math.round(100 * x);
  return <span style={{ color: v >= 80 ? "var(--good)" : v >= 30 ? "var(--warn)" : "var(--bad)" }}>{v}%</span>;
}

export default function DataSources() {
  const { status, reloadStatus } = useStatus();
  const comps = useFetch<Competition[]>("/api/competitions");
  const runs = useFetch<G[]>("/api/import/runs");
  const links = useFetch<G>("/api/teams/links");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<G | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [localPath, setLocalPath] = useState("");
  const [alias, setAlias] = useState<{ name: string; q: string; results: string[] }>({ name: "", q: "", results: [] });
  const doImport = async (body: G = {}, path = "/api/import") => {
    setBusy(true); setErr(null); setResult(null);
    try { const r = await api<G>(path, { method: "POST", json: body }); setResult(r); reloadStatus(); comps.reload(); runs.reload(); links.reload(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const search = async (q: string) => { setAlias({ ...alias, q }); if (q.length >= 2) setAlias({ ...alias, q, results: await api<string[]>(`/api/teams/search?q=${encodeURIComponent(q)}`) }); };
  const saveAlias = async (target: string) => { await api("/api/teams/aliases", { method: "POST", json: { alias_name: alias.name, target_team_id: target } }); setAlias({ name: "", q: "", results: [] }); links.reload(); };
  const d = status?.dataset;
  return (
    <div className="page">
      <div className="page-head"><div><h1>Data sources</h1><p>All sources are free. Nothing is scraped from sites that do not permit it, and no paid API is used.</p></div></div>
      <div className="grid g2" style={{ marginBottom: 12 }}>
        <Panel title="Source A — Open-Matchday" sub="free CSV dataset, refreshed daily upstream">
          <dl className="kv small">
            <dt>Repository</dt><dd><a href="https://github.com/oladeeayo/open-matchday" target="_blank" rel="noreferrer">github.com/oladeeayo/open-matchday</a></dd>
            <dt>Dataset build</dt><dd>{d?.generated_utc ?? "not imported"} {d?.age_days != null && <Chip tone={d.age_days <= 1 ? "good" : d.age_days <= 3 ? "warn" : "bad"}>{d.age_days.toFixed(1)} days old</Chip>}</dd>
            <dt>Imported</dt><dd>{d ? `${d.imported_at} via ${d.method}${d.commit_sha ? ` · commit ${d.commit_sha.slice(0, 10)}` : ""}` : "—"}</dd>
            <dt>Contents</dt><dd>{d ? `${d.competitions} competitions · ${d.results} results · ${d.fixtures} fixtures` : "—"}</dd>
            <dt>Terms</dt><dd>Informational, non-commercial use with attribution. Provider rights (football-data.co.uk, ESPN, FotMob, Soccerway, OpenLigaDB, fixturedownload) stay with the providers. Do not sell or redistribute the data commercially.</dd>
          </dl>
          <div className="row" style={{ marginTop: 10 }}>
            <button className="primary" onClick={() => doImport()} disabled={busy}>{busy ? "Importing…" : "Download & import latest"}</button>
            <button onClick={() => doImport({}, "/api/import/reprocess")} disabled={busy}>Re-process downloaded data</button>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <input placeholder="…or a local clone path, e.g. ~/open-matchday" value={localPath} onChange={(e) => setLocalPath(e.target.value)} style={{ flex: 1 }} />
            <button onClick={() => doImport({ local_path: localPath })} disabled={busy || !localPath}>Import local folder</button>
          </div>
          <p className="tiny muted" style={{ marginTop: 6 }}>Download order: GitHub ZIP → raw.githubusercontent.com per file → jsDelivr mirror. Blank values stay missing (never zero). The odds snapshot files in the dataset (Flashscore pre-match quotes for bet365, Betway, Betano) are imported as labelled reference prices only.</p>
          <ErrorBox error={err} />
          {result && <div className="notice good small" style={{ marginTop: 8 }}>Imported {result.competitions ?? ""} competitions · {result.results} results · {result.fixtures} fixtures{result.snapshot_prices != null ? ` · ${result.snapshot_prices} snapshot prices` : ""}. {result.settlement ? `Settled ${result.settlement.settled} predictions.` : ""}{result.warnings?.length ? ` ${result.warnings.length} warnings.` : ""}</div>}
        </Panel>
        <div className="stack">
          <Panel title="Source B — Public statistics websites (manual)">
            <p className="small">Sites such as <a href="https://footiqo.com/" target="_blank" rel="noreferrer">footiqo.com</a> are used as supporting research. MatchEdge does not scrape them: each match page generates links, you check the page yourself, and paste the relevant statistic with the URL and time checked. Those entries appear as evidence in the analysis.</p>
          </Panel>
          <Panel title="Source C — Bet365 prices (manual)">
            <p className="small">You enter prices by hand on each match page (bookmaker, market, selection, line, decimal odds, time checked). MatchEdge never logs in to Bet365, stores no credentials, and labels every price as a manual entry — never as a verified live price.</p>
          </Panel>
          <Panel title="Source D — Your research notes">
            <p className="small">URL, statistic, notes, time checked and reliability, with any number of sources per match. Lineup or injury notes can reject a match. Nothing is cited that you did not enter.</p>
          </Panel>
        </div>
      </div>

      <Panel title="Competition coverage" sub="share of result rows with each statistic — check before relying on a stat" tight>
        {comps.loading ? <Loading /> : (
          <div className="tbl-wrap" style={{ maxHeight: 520 }}><table className="tbl">
            <thead><tr><th>Competition</th><th>Country</th><th className="num">Results</th><th className="num">Fixtures</th><th className="num">Latest</th><th className="num">Kickoff time</th><th className="num">Half-time</th><th className="num">Shots</th><th className="num">Corners</th><th className="num">Cards</th><th className="num">Odds snap.</th></tr></thead>
            <tbody>{(comps.data ?? []).map((c) => (
              <tr key={c.code}><td>{c.name}<div className="muted tiny">{c.code}</div></td><td>{c.country}</td><td className="num">{c.n_results}</td><td className="num">{c.n_fixtures}</td><td className="num small">{c.latest_result ?? "—"}</td>
                <td className="num">{cov(c.coverage.kickoff_time)}</td><td className="num">{cov(c.coverage.half_time)}</td><td className="num">{cov(c.coverage.shots)}</td><td className="num">{cov(c.coverage.corners)}</td><td className="num">{cov(c.coverage.cards)}</td><td className="num">{c.has_odds ? "yes" : "—"}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Panel>
      <div style={{ height: 12 }} />
      <div className="grid g2">
        <Panel title="Team links across competitions" sub="UEFA files use short names" tight>
          {links.loading ? <Loading /> : (
            <div className="panel-b">
              <p className="small muted">Teams in UEFA competitions are linked to their domestic data by exact name key or a checked alias. Ambiguous names are never guessed. Unlinked teams only use their UEFA matches.</p>
              {(links.data?.unlinked ?? []).length === 0 ? <Empty>All teams linked.</Empty> : (
                <table className="tbl"><thead><tr><th>Name</th><th>Status</th><th>Candidates</th><th></th></tr></thead>
                  <tbody>{links.data!.unlinked.map((u: G) => <tr key={u.name}><td>{u.name}</td><td><Chip tone="warn">{u.method}</Chip></td><td className="small">{u.candidates.join(", ") || "no domestic data in dataset"}</td><td><button className="sm" onClick={() => setAlias({ name: u.name, q: "", results: [] })}>Link…</button></td></tr>)}</tbody></table>
              )}
              {alias.name && (
                <div className="notice" style={{ marginTop: 8 }}>
                  <div className="row"><b>Link “{alias.name}” to:</b><input placeholder="search domestic team" value={alias.q} onChange={(e) => search(e.target.value)} autoFocus /><button className="sm ghost" onClick={() => setAlias({ name: "", q: "", results: [] })}>Cancel</button></div>
                  <div className="row" style={{ marginTop: 6 }}>{alias.results.map((r) => <button key={r} className="sm" onClick={() => saveAlias(r)}>{r}</button>)}</div>
                  <div className="tiny muted" style={{ marginTop: 4 }}>After saving, click “Re-process downloaded data”.</div>
                </div>
              )}
            </div>
          )}
        </Panel>
        <Panel title="Aliases in use" tight>
          {(links.data?.aliases ?? []).length === 0 ? <Empty>None.</Empty> : (
            <div className="tbl-wrap" style={{ maxHeight: 320 }}><table className="tbl"><thead><tr><th>Name key</th><th>Linked to</th><th>Origin</th><th></th></tr></thead>
              <tbody>{links.data!.aliases.map((a: G) => <tr key={a.alias_key}><td>{a.alias_key}</td><td>{a.target_team_id}</td><td><Chip tone={a.origin === "user" ? "info" : ""}>{a.origin}</Chip></td><td>{a.origin === "user" && <button className="sm ghost danger" onClick={async () => { await api(`/api/teams/aliases/${encodeURIComponent(a.alias_key)}`, { method: "DELETE" }); links.reload(); }}>Remove</button>}</td></tr>)}</tbody></table></div>
          )}
        </Panel>
      </div>
      <div style={{ height: 12 }} />
      <Panel title="Import history" tight>
        <table className="tbl"><thead><tr><th>#</th><th>Started</th><th>Status</th><th>Method</th><th>Dataset build</th><th className="num">Results</th><th className="num">Fixtures</th><th>Warnings / error</th></tr></thead>
          <tbody>{(runs.data ?? []).map((r) => <tr key={r.id}><td>{r.id}</td><td className="num small">{r.started_at}</td><td><Chip tone={r.status === "ok" ? "good" : r.status === "failed" ? "bad" : "info"}>{r.status}</Chip></td><td>{r.method}</td><td className="small">{r.dataset_generated_utc ?? "—"}</td><td className="num">{r.n_results ?? ""}</td><td className="num">{r.n_fixtures ?? ""}</td><td className="small muted">{r.error ?? (r.warnings?.warnings?.length ? `${r.warnings.warnings.length} warnings` : "")}</td></tr>)}</tbody></table>
      </Panel>
      <p className="tiny muted" style={{ marginTop: 10 }}>{status?.attribution}</p>
    </div>
  );
}
