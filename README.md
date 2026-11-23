# MatchEdge Local

A private, zero-cost football betting **research** agent that runs entirely on your computer.

It imports free public match data, runs a transparent statistical engine (no AI needed),
compares markets, rejects matches that are not worth betting, and builds accumulators from
**prices you enter yourself** — without padding a ticket with weak selections just to reach a
target. An optional local model (Ollama) can rewrite the analysis in plain language; its output
is checked against the data and discarded if it invents anything.

> **No paid services.** No football/odds/stats APIs, no OpenAI/Claude/Gemini, no paid database,
> no paid hosting, no scraping services. Nothing is sent to an AI provider.
> Estimates are model outputs, not verified probabilities. Nothing here is financial advice.

---

## Quick start

Requirements: **Python 3.10+** and **Node.js 18+** (Node is only needed to build the interface once).

```bash
git clone <this repository> matchedge && cd matchedge
```

macOS / Linux:

```bash
./start.sh
```

Windows (Command Prompt or PowerShell, inside the project folder):

```bat
start.bat
```

In PowerShell type `.\start.bat`. Install Python from python.org with **"Add python.exe to PATH"**
ticked, and Node.js LTS from nodejs.org, then open a *new* terminal before the first run.

The script creates a virtual environment, installs the Python packages, builds the interface,
downloads the Open-Matchday dataset on first run, and opens **http://127.0.0.1:8000**.

| Command | What it does |
|---|---|
| `./start.sh` | start (installs/builds/imports only what is missing) |
| `./start.sh --import` | re-download the dataset, then start |
| `./start.sh --test` | run backend and frontend tests |
| `MATCHEDGE_PORT=8080 ./start.sh` | use another port |

The server binds to `127.0.0.1` only. Your database lives in `data/matchedge.sqlite3`
(git-ignored); delete it to start over.

### Weekly plan

The **Weekly plan** page builds three separate ticket slots for any week (Monday–Sunday, Europe/Belgrade):

| Slot | Days | Competitions |
|---|---|---|
| Champions League | Tuesday & Wednesday | UEFA Champions League |
| Europa + Conference League | Thursday | UEFA Europa League and Conference League together |
| Weekend leagues | Saturday & Sunday | European top divisions by default (choose your own leagues on the page) |

Each slot gets one ticket per target — **50 and 110** by default (change on the page or in
Settings → `plan_targets`). The builder uses only well-supported, priced selections and stops at
the target; if a slot cannot reach a target honestly it says so, and when both targets would need
the same legs the page shows one ticket instead of two copies. Weeks without European matches show
the UEFA slots as empty. The two tickets in a slot usually share legs — the page tells you how many.
Weekly-plan tickets may use up to `plan_max_legs` (default 14) legs; each ticket shows the model's
estimated chance of every leg winning next to the bookmaker's implied chance.

Routine: import data → open Weekly plan → enter your own Bet365 prices for the listed legs (or
replace snapshot prices) → **Rebuild** → **Save & track** the tickets you place.

### Pasting odds from Bet365

Typing prices is the slowest part of the routine, so you can paste them instead. On the Bet365 page,
select a market (heading, selections and prices) or a whole coupon list, copy, and paste into
**Paste from Bet365** on a match's Odds tab, or into the bulk box on the Weekly plan page. The
parser understands match lines ("Arsenal v Dortmund"), coupon layouts (two team lines followed by
three prices), the common market headings, Over/Under lines, Asian lines like "-0.5,-1.0", and
decimal, fractional and EVS prices. Every recognised price is shown in a preview with the text it
came from; you untick or correct anything, then save. Unsupported markets (correct score,
scorers…) and lines it cannot read are listed, never guessed. Nothing logs in to Bet365.

### Profit backtest, closing-line value and the model check (Historical performance)

* **Profit backtest** replays the weekend plan for every weekend of the last five seasons using
  only data available before each match and Bet365's real pre-match prices. First run (204 weekends,
  2021/22–2025/26): the selected legs won **60%** while the model expected 70% and Bet365's prices
  implied 61%; as singles they returned about −2% per bet, beat the closing price only 39% of the
  time, and the weekend tickets returned about −7.5%. **On these markets the model shows no edge
  over Bet365** — treat its probabilities as research input, not as an advantage. Historical prices
  exist only for 1X2, Over/Under 2.5 and the main Asian line, and UEFA matches are not in the files.
* **Closing-line value** compares the price you took with Bet365's closing price (true close from
  football-data for 1X2, Over/Under 2.5 and the main Asian line; otherwise the last daily snapshot,
  marked approximate). Consistently positive CLV is the earliest reliable sign of a real edge.
* **Odds archive**: every import archives changed snapshot prices, so each match shows Bet365's
  price movement and CLV becomes available for more markets over time.
* **League strength** for Champions/Europa/Conference League matches is learned from this season's
  European results (see docs/MODEL.md); walk-forward on 124 UEFA matches it predicted better than
  the old fixed shrinkage (log loss 1.658 vs 1.678).

### Daily routine

1. **Data sources → Download & import latest** (the dataset is rebuilt upstream every day at 00:00 UTC).
   The first import also downloads five past seasons from football-data.co.uk (about 130 small files,
   1–2 minutes); later imports only refresh the current season.
2. **Upcoming fixtures**: pick a date. Verify kickoff times you intend to use on the official site.
3. **Match research**: enter your Bet365 prices (Odds tab) and any research (Research tab).
4. **Accumulator builder**: click selections into the slip, or auto-build toward your target.
5. **Save & track**: the next import settles your selections automatically.

### Manual setup (if you prefer)

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install && npm run build)
cd backend
../.venv/bin/python -m matchedge import          # or: import --local ~/open-matchday
../.venv/bin/python -m matchedge serve           # http://127.0.0.1:8000
```

Development with hot reload: run `python -m matchedge serve` in `backend/` and `npm run dev` in
`frontend/` (Vite on :5173 proxies `/api` to :8000).

---

## Data sources

| | Source | How it is used |
|---|---|---|
| **A** | [Open-Matchday](https://github.com/oladeeayo/open-matchday) CSVs (75 competitions, 2026/27) | Downloaded and validated locally: fixtures, results, half-time scores, shots, fouls, cards, corners, goal minutes. |
| **A2** | [football-data.co.uk](https://www.football-data.co.uk/) CSVs (22 European divisions, current + 5 past seasons) | Results, stats, referees and Bet365 opening/closing odds. Feeds previous-season form, the profit backtest and closing-line value. Free for personal, non-commercial use; kept on your computer. |
| **B** | Public statistics sites such as [footiqo.com](https://footiqo.com/) | **Not scraped.** Each match page generates links; you read the page and paste the statistic with the URL and time you checked. |
| **C** | Bet365 prices | **Manual entry only.** No login automation, no credentials stored, never labelled as live odds. |
| **D** | Your research notes | URL, statistic, value, notes, time checked, reliability, effect on a market. Multiple per match. |

**Importer.** Tries the GitHub ZIP archive (one request; carries the commit SHA), then
`raw.githubusercontent.com` per file, then the jsDelivr mirror. You can also point it at a
local `git clone`. Every CSV header is validated against the documented schema; **blank cells
stay NULL — never zero**. Team names are normalised (see below) and dataset freshness comes from
`build_summary.json`.

**Odds snapshots.** The dataset also publishes Flashscore pre-match quotes (bet365, Betway,
Betano) for about 45 competitions. MatchEdge imports them as *reference snapshots* labelled
with their capture time. Your manual entries always take precedence, and every ticket shows
which prices are snapshots. You can disable snapshots entirely in Settings.

**Coverage is uneven** (see the coverage table on the Data sources page): shots, fouls, cards and
corners exist mainly for leagues covered by football-data.co.uk/FotMob; half-time scores for
about a fifth of all rows; there are no lineups, injuries, referees, xG or prior seasons in the
dataset. Statistics that are missing are shown as missing, and markets that need them are
marked *unsupported*.

**Team names.** Providers spell clubs differently ("Stade Rennais FC" / "Stade Rennais" /
"Rennes", "B. Dortmund" / "Borussia Dortmund"). A canonical key (transliteration, punctuation,
club-type tokens like FC/SC/VfB) unifies spellings inside each league. UEFA teams are linked to
their domestic data by exact key or a checked alias list; ambiguous names (e.g. "Paris" vs
"Paris FC") are **never guessed** and can be linked by you on the Data sources page.

**Timezone.** Everything is shown in **Europe/Belgrade**. The dataset uses a fixed UTC+1
convention, so on summer-time dates a time may be an hour off; each fixture carries a
certainty label (corroborated by the odds snapshot, single source, ±1 h, unknown, conflict, or
set by you). A fixture stays *unverified* until you confirm it with an official URL.
Started, completed, postponed, cancelled and vanished fixtures cannot go on a pre-match ticket,
and a match with an unknown kickoff on today's date is excluded until you set its time.

**Terms.** Open-Matchday is free for informational, **non-commercial** use with attribution;
upstream provider rights remain with football-data.co.uk, ESPN, FotMob, Soccerway, OpenLigaDB
and fixturedownload. This project does not redistribute the dataset (it is downloaded to your
machine and git-ignored). Do not use it to build a commercial product.

---

## How the analysis works

Full details: [`docs/MODEL.md`](docs/MODEL.md) (statistics and probability models) and
[`docs/SCORING.md`](docs/SCORING.md) (scores, gates, rejection rules, accumulator).

* **Descriptive statistics** — form (last 5/10), home/away splits, goals (Over 1.5/2.5/3.5,
  Under 2.5, BTTS, clean sheets, first/second-half goals), corners, cards, fouls, shots and
  shots on target. Every figure reports its sample size and completeness; small samples carry
  a warning.
* **Goal model** — independent Poisson with venue-adjusted, league-relative attack/defence
  ratings, recency weighting, shrinkage toward league average, a cap on extreme scores, and an
  explicit approximation for cross-league fixtures. Each probability has an uncertainty range;
  with too little data the answer is "Insufficient data".
* **Corners & cards** — negative binomial on match totals with competition-measured dispersion.
* **Five separate outputs** — match research score, model probability, bookmaker implied
  probability, data-quality score and risk assessment are never blended into one number.
* **Market comparison** — 1X2, double chance, draw no bet, goal totals, BTTS, team goals,
  first-half goals, corners, cards and Asian handicap (only when priced). The engine recommends
  the most defensible market and explains why the alternatives (always including the match
  winner) lose — or recommends nothing.
* **Rejection system** — small samples, closely matched teams, erratic form, conflicting
  evidence, lineup/injury uncertainty you recorded, outdated data, no market passing the gates.
* **Accumulator** — combined odds = product of prices; duplicates and same-match selections are
  blocked, same-team and same-round correlations are flagged; the builder stops at the target
  and never pads. If the target is unreachable it says so, shows what padding would cost, and
  proposes a smaller alternative.
* **Model check** — every finished league match of the season is re-predicted using only earlier
  matches and compared with the result (Historical performance page). The default shrinkage
  (12 pseudo-matches) and recency half-life (16 matches) were chosen from this check: they gave the
  lowest log loss and cut overconfidence on 80 %+ predictions from about 3 points to about 1.
  Remaining weak spot: Under 3.5 goals is still ~5 points overconfident at the top end.
* **Tracking** — saved tickets record price, model estimate and data quality at prediction time;
  imports settle them from real results (markets whose statistic is missing need manual
  settlement). Dashboards: overall, goals, corners, cards, match winner, odds ranges and
  calibration with confidence bands. No claim of improvement is made without data.

### Optional local AI (Ollama)

1. Install [Ollama](https://ollama.com/) and pull a model: `ollama pull llama3.1:8b`.
2. Settings → *Optional local AI* → enable, check the status indicator.
3. On a match page click **Ask local AI**, or tick the AI summary in the accumulator builder.

Only loopback addresses are contacted unless you explicitly allow another host you own. The
model receives the engine's structured JSON and must cite the fields it used. Output that cites
non-existent fields or contains numbers not present in the data is rejected and the
deterministic explanation is shown instead — the app is fully functional without Ollama.

---

## Project layout

```
backend/matchedge/
  importer.py        download, validate, normalise, store (Open-Matchday)
  teamnames.py       canonical keys + cross-competition linking
  timeutil.py        UTC+1 dataset convention → Europe/Belgrade, certainty labels
  engine/
    data.py          in-memory store of team-perspective rows
    stats.py         missing-aware descriptive statistics
    poisson.py       goal model, settlement for AH/quarter lines
    countmodel.py    corners & cards (negative binomial)
    markets.py       candidate markets, prices, implied/fair probability, scores, gates
    scoring.py       research score, data quality, risk
    rejection.py     rejection rules
    analysis.py      orchestration, pre-match eligibility
    explain.py       deterministic analyst explanations
    accumulator.py   combined odds, validation, correlations, builder, final opinion
    report.py        final accumulator report
    tracking.py      settlement and performance dashboards
  ai/ollama.py, ai/validator.py   optional local model + output validation
  main.py            FastAPI app (also serves the built UI)
backend/tests/       unit + integration tests (synthetic dataset, no network)
frontend/src/        React + TypeScript + Recharts UI (8 pages)
docs/                MODEL.md, SCORING.md
```

## Tests

```bash
./start.sh --test
# or
cd backend && ../.venv/bin/python -m pytest
cd frontend && npx vitest run
```

Covered: Poisson identities and closed forms, Asian/quarter-line settlement, shrinkage and goal
caps, missing-data handling (blank ≠ 0), UTC+1 → Belgrade conversion including summer time,
exclusion of started/completed/postponed fixtures, duplicate and same-match selections,
correlation warnings, the no-padding builder, local-AI fallback (disabled, unreachable,
invented numbers, bad citations, non-local host), importer validation and download fallback,
and an end-to-end flow through the HTTP API from import to automatic settlement.

## Limitations (read these)

* One season of data only — no prior-season form; early-season and promoted-team estimates rely
  on shrinkage.
* Independent Poisson ignores goal correlation and under-states blow-outs; deep handicaps are
  therefore not auto-suggested.
* Cross-league strength (UEFA, cups between tiers) is an approximation and is labelled as such.
* No lineups, injuries, referees, weather or motivation in the data — that is what the research
  panel is for.
* Scores and gates are transparent heuristics, not validated betting edges. Track your results
  and judge the model by its calibration, not by single tickets.
