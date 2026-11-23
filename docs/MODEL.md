# Statistics and probability models

All calculations are deterministic and run locally. Code: `backend/matchedge/engine/`.

## 1. Inputs and samples

* Finished matches are turned into **team-perspective rows** (`data.py`): for each match, one row
  per team with every statistic as "for" and "against".
* Only matches **strictly before** the fixture date are used (no look-ahead).
* **League fixtures:** the team's matches in the same competition. If fewer than
  `min_matches_model`, all competitions are used and the sample is flagged as mixed.
* **Cups / UEFA:** all of the team's matches across competitions (linked by team identity), with
  each match rated relative to its own competition's baseline (see §3).
* **Missing values are never zero.** A statistic's mean uses only rows where it exists; every
  output carries `n` (usable matches), `of` (matches considered) and completeness. Fewer than
  `min_matches_stat` usable matches → warning; zero → "not provided by the dataset".

## 2. Descriptive statistics (`stats.py`)

Last 5 / last 10: W-D-L, goals for/against, win %, points per game, sequence.
Venue split: home team at home, away team away.
Goals: averages, Over 1.5/2.5/3.5, Under 2.5, BTTS, clean sheets, failed to score, 2+ scored,
first-half goal rate, first- and second-half goal averages (from half-time scores).
Corners, cards (yellow, red, total), fouls, shots, shots on target, last five matches with corner
data, scoring consistency.

## 3. Goal model (`poisson.py`)

Independent Poisson. For a fixture in competition *C* on date *d*:

**Baseline.** `μH`, `μA` = mean home/away goals in *C* before *d*. With fewer than
`min_league_matches` (default 30) results, a pooled baseline across all competitions is used and
reported.

**Ratings.** For team *T* with matches *i = 0 (latest) … n-1*:

```
w_i      = 0.5 ^ (i / recency_half_life)                       # recency weighting
attack   = (Σ w_i · min(goals_for_i, cap)     / μ_for(venue_i, comp_i)     + k) / (Σ w_i + k)
defence  = (Σ w_i · min(goals_against_i, cap) / μ_against(venue_i, comp_i) + k) / (Σ w_i + k)
```

* `cap` = `goal_cap` (default 5) limits the influence of extreme results.
* `k` = `prior_weight` (default 4) pseudo-matches of league average (rating 1.0). This is the
  safeguard for small samples, newly promoted teams and early-season noise — there is no
  prior-season data in the dataset.
* Each match is compared with the baseline **of the competition it was played in**, so a cup
  match against a lower-division side is not judged by Premier League scoring rates.

**Expected goals.**

```
λ_home = attack_H · defence_A · μH
λ_away = attack_A · defence_H · μA
```

**Cross-league fixtures** (UEFA competitions, cups between leagues): ratings measured in
different leagues are not comparable, so each rating's deviation from 1.0 is multiplied by
`cross_league_shrink` (default 0.5). The output is labelled an approximation, confidence is
capped at "medium", and a −8 score adjustment applies.

**Score matrix** up to 10 goals each side, renormalised. From it: 1X2, double chance, draw no
bet (conditional on no draw), Over/Under 0.5–4.5, BTTS, team totals, and a general settlement
function for Asian handicaps and whole/quarter goal lines (win / half-win / push / half-loss /
loss).

**First half.** λ × the competition's share of goals scored before half-time (from matches with
half-time scores; pooled if the competition lacks them). First-half markets are only
*supported* when both teams have at least `min_matches_stat` matches with half-time scores.

**Uncertainty.** Each λ gets a relative standard error

```
e = sqrt( 1 / (G_for + k·μ) + 1 / (G_against + k·μ) )
```

where `G_for`, `G_against` are the recency-weighted goal counts behind the two ratings and `k·μ`
the prior's pseudo-goals (a Gamma–Poisson posterior approximation). Every market is recomputed at
`λ·(1 ± e)` for both teams; the min/max become the reported range. Point estimates are rounded
to whole percentages.

**Insufficient data.** If either team has fewer than `min_matches_model` matches (default 5),
the model returns `"Insufficient data"` and goal markets are unsupported.

**Calibration of the defaults.** `prior_weight = 12` and `recency_half_life = 16` were chosen by a
walk-forward check on 5,553 finished 2026/27 league matches (each predicted from earlier matches
only; `engine/backtest.py`, shown on the Historical performance page). Grid tested: prior 4–30 ×
half-life 8/16/∞. Prior 4 / half-life 8 (the first version) was overconfident by ~3 points on
predictions of 80 %+; prior 12 / half-life 16 had the lowest log loss and ~1 point. Choosing two
parameters on the same season is mild in-sample tuning — keep watching the check as data grows.

**Previous season (football-data.co.uk).** For league fixtures the model also uses the team's
matches from the previous season in the same competition, each weighted by `history_carryover`
(0.75) on top of the recency decay — squads change in summer. Descriptive statistics and hit rates
stay current-season only. Walk-forward log loss (1X2 + Over 2.5 + BTTS, early-season matches):
2025/26 0.6528 → 0.6459, 2026/27 0.6370 → 0.6343; later in the season the gain is small.
Promoted teams have no previous-season matches in their new league and rely on shrinkage.

**League strength for UEFA fixtures** (`engine/strength.py`). Each team is rated inside its own
domestic league; each league gets a strength S_L learned from this season's Champions/Europa/
Conference League results by penalised Poisson maximum likelihood (Normal(0, 0.35²) prior):
`λ_home = μ_home·att·def·exp((S_home − S_away)/2)`, `λ_away = μ_away·att·def·exp((S_away − S_home)/2)`.
The posterior variance of the gap is added to each λ's uncertainty, so leagues with few European
matches get wide ranges. Walk-forward on 124 UEFA matches: log loss 1.658 vs 1.678 for the previous
fixed 50 % shrinkage. Domestic cups between divisions keep the shrinkage method (lower divisions
never meet in Europe; fitting them from cup ties produced implausible orderings).

**Profit backtest** (`engine/plan_backtest.py`): see README. The key finding — selected legs won 60 %
vs 70 % expected and 61 % implied — shows the model's edge over Bet365 is not real on the main
markets: choosing bets where the model disagrees most with the bookmaker mostly selects model errors.

### Known limitations

* Independence ignores the small negative/positive correlation of the two teams' goals and
  under-states large margins; snapshot handicap lines beyond ±1.5 are therefore not considered.
* No xG, lineups, injuries, weather, motivation or referee in the data.
* One season only.

## 4. Corners and cards (`countmodel.py`)

```
E[home corners] = ½ · ( shrink(home team corners for, at home) + shrink(away team corners against, away) )
E[away corners] = ½ · ( shrink(away team corners for, away)    + shrink(home team corners against, at home) )
shrink(x, n)    = (n·x + k·league_mean) / (n + k)
```

Venue-specific samples are used when each side has at least `min_matches_stat`; otherwise all
venues. The match total is modelled with a **negative binomial** with variance = mean × the
competition's measured variance/mean ratio (corners and cards are over-dispersed). Without
enough team or league data the market is unsupported.

Cards: total = yellow + red as listed in the dataset. Bookmakers often settle differently
(booking points, second-yellow rules) — check before betting. Referee data is not available.

## 5. Historical hit rates (`markets.py`)

For every candidate selection, the engine evaluates the exact settlement condition on past
matches: the home team's home matches, the away team's away matches, and each team's last ten.
Rows where the condition cannot be evaluated (missing statistic, a push) are skipped, not
counted as losses.

## 6. Bookmaker probabilities

* Implied probability = 1 / decimal odds (includes the bookmaker margin).
* Margin-free ("fair") probability when the complementary selections from the same bookmaker and
  source are priced: `(1/oᵢ) / Σ(1/oⱼ)`; the overround is reported.
* Edge = model probability − implied probability. A very large positive edge (> 20 points) is
  treated as a **warning**, not an opportunity: the price probably reflects information the
  dataset does not have.
