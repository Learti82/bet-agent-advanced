# Scores, gates, rejection rules and the accumulator

These are **transparent heuristics**. The weights below were chosen to encode a skeptical
analyst's priorities; they have not been fitted to betting outcomes and are not validated
probabilities. Use the Historical performance page to judge them over time.

Five quantities are kept separate and never blended:

| Quantity | Range | Meaning |
|---|---|---|
| Match research score | 0–100 | How clear and well-evidenced the statistical picture is. Not a probability, not a direction. |
| Model probability | 0–100 % + range | Poisson / negative-binomial estimate for one selection. |
| Bookmaker implied probability | 0–100 % | 1/odds (and margin-free when the full market is priced). |
| Data quality score | 0–100 | How trustworthy the inputs are. |
| Risk assessment | low / medium / high | Named risk factors from the rejection rules. |

## Match research score (`scoring.py: research_score`)

| Component | Max | Rule |
|---|---|---|
| Recent form | 15 | 15 × min(1, \|last-5 ppg gap\| / 1.5) |
| Home/away | 15 | 15 × min(1, \|home team home ppg − away team away ppg\| / 1.5) |
| Goals signal | 15 | 15 × min(1, \|model total − competition average\| / 1.0) |
| Attack/defence mismatch | 10 | 10 × min(1, \|log(attH·defA) − log(attA·defH)\| / 0.8) |
| Secondary stats | 10 | 5 if the corners model is available, 5 if the cards model is |
| Sample size | 15 | 15 × min(1, smallest team sample / 10) |
| Freshness | 10 | −2 per day of dataset age beyond 1 (max −5); −1 per week a team's last result is older than 14 days (max −3 each) |
| Consistency | 10 | 5 × goal-volatility term + 5 × (1 − last-5 vs last-10 ppg drift / 1.2) |

A clear mismatch with plenty of fresh, consistent data scores high. A coin-flip fixture with thin
data scores low — which is information, not a failure.

## Data quality score (`scoring.py: data_quality`)

| Component | Max | Rule |
|---|---|---|
| Sample | 30 | 30 × min(1, smallest team sample / 10) |
| Completeness | 25 | 10 (goals always present) + 15 × weighted coverage of half-time 20 %, shots 20 %, corners 30 %, cards 30 % |
| Freshness | 20 | 20 × (1 − max(0, dataset age − 1 day) / `max_dataset_age_days`) |
| Fixture certainty | 15 | verified by you 15; corroborated time 11; single source 8; ±1 h 5; conflict 4; unknown 0 |
| Team identity | 10 | same-competition sample 10; mixed competitions via name links 6; unlinked team 0 |

Label: good ≥ 70, fair ≥ 50, otherwise poor.

## Selection score (`markets.py: score_candidate`)

Evidence (max 85) + price (max 15) = score (max 100).

| Component | Max | Rule |
|---|---|---|
| Probability | 40 | 40 × clamp((p_c − 0.50) / 0.35), where p_c = p − ½(p − lower end of range). Uncertainty lowers the score. |
| Historical agreement | 20 | 20 × clamp((min(home hit rate, away hit rate) − 0.45) / 0.40) × (1 − clamp((\|p − mean hit rate\| − 0.10) / 0.25)). Uses venue samples, or last-10 if a venue sample has < 3 matches. |
| Sample | 15 | 15 × min(1, smallest hit-rate sample / 10) |
| Completeness | 10 | 10 × usable / considered matches for the statistic |
| Price | 15 | 15 × clamp((edge + 0.05) / 0.15), only when a price exists |

Adjustments: model vs history disagreement > `conflict_threshold` (0.22) −10; cross-league −8;
edge > 0.15 −5 (suspiciously large); each medium/high-reliability research note that
contradicts the selection −10; supporting notes +3 each (max +6).

Tiers: strong ≥ `strong_selection_score` (68), acceptable ≥ `min_selection_score` (55), else weak.
Confidence: high = strong + data quality ≥ 70 + risk not high (capped at medium for cross-league);
medium = acceptable + data quality ≥ 50; otherwise low.

## Gates — when a selection may go on a ticket

A candidate *qualifies* only if all hold:

1. The data it needs exists (model available; corners/cards/half-time samples sufficient).
2. Model probability ≥ `min_leg_probability` (0.60) and the range's lower end ≥ that − 0.08.
3. No model-vs-history conflict.
4. Price ≥ `min_leg_odds` (1.30) — or, without a price, fair odds (1/p) ≥ 1.30. Very short prices
   add almost nothing to a ticket but carry full risk.
5. Price not more than 10 points worse than the model (edge ≥ −0.10).
6. Model not more than 20 points above the price (edge ≤ 0.20) — a gap that large usually means
   the market knows something the dataset does not.
7. Evidence score ≥ `min_evidence_score` (35).
8. No medium/high-reliability research note contradicting it.
9. Half line (whole and quarter lines can push or half-settle, so they are shown but kept off tickets).
10. Not a match-result market (1X2, DNB, AH) when the teams are closely matched.

The **recommended market** is the qualifying candidate with the highest evidence score. The
match-winner market is always included in the comparison with the reason it lost.

## Rejection rules (`rejection.py`)

| Rule | Severity / action |
|---|---|
| Smallest team sample < `min_matches_model` | high / reject |
| Goal model unavailable | high / reject |
| Lineup or injury uncertainty in your research (medium/high reliability, not "supports") | high / reject |
| No market reaches `min_leg_probability` | high / reject |
| Dataset older than `max_dataset_age_days` | high / reject |
| No market passes the gates | high / reject |
| Not pre-match (started, completed, postponed, cancelled, vanished, unknown time today) | ineligible |
| Limited sample (< 8) | medium / flag |
| Team not linked to domestic data | medium / flag |
| Closely matched (xG gap < `close_match_xg_gap` and last-5 ppg gap < 0.6) — result markets excluded | medium / flag |
| Erratic form (4 result changes in last 5) | medium / flag |
| ≥ 2 of the six most likely markets conflict with history | medium / flag |
| Team's last result > `team_stale_days` before kickoff | medium / flag |
| Cross-league comparison | medium / flag |
| Kickoff unknown, ±1 h or conflicting | medium / flag |
| Last-5 vs last-10 form swing ≥ 0.8 ppg | low / flag |
| No lineup info; fixture unverified; qualifying markets unpriced | info |

Status: **rejected** if any reject rule fires; **flagged** if a medium/high flag fires;
otherwise **candidate**. Every rejected match lists its reasons, missing information and any
markets that could still be considered.

## Accumulator (`accumulator.py`)

* Combined odds = o₁ × o₂ × … × oₙ.
* **Errors (ticket invalid):** duplicate selection; two selections from one match; missing price;
  started or otherwise non-pre-match fixture.
* **Correlation warnings:** same match (strong); same team in two matches (moderate); three or
  more selections of the same market family in one competition on one day (weak).
* **Other warnings:** weak or non-qualifying legs, snapshot prices, unverified fixtures,
  uncertain kickoff times.
* "Naive model estimate" = product of leg probabilities, explicitly assuming independence.

**Builder.** Pool = best priced qualifying selection per non-rejected match, split into
strong/acceptable legs with high/medium confidence and the rest ("weak"). Only the first group is
used for the ticket. Within it, legs are ordered by *probability cost per unit of odds*,
`log(1/p) / log(odds)` (×1.15 for legs from flagged matches): for a fixed target the chance of the
whole ticket is Π p subject to Σ log(odds) ≥ log(target), so the cheapest legs give the best
estimated ticket. The builder adds legs until the target is reached or `max_legs` (weekly plan:
`plan_max_legs`) is hit, never using the same team twice, then drops the least likely legs while
the target still holds. If it stopped because of the leg limit, the report says so. If the target is not reached it **stops** — the report states that the target is
unreachable with well-supported legs, shows (separately, marked not recommended) the weak legs
padding would require and the resulting probability, and proposes a smaller alternative of the
2–4 best legs.

**Final opinion** states directly whether the ticket is well-supported, or has been made riskier
to hit the target, and quotes both the naive model estimate and the bookmaker's implied
probability.
