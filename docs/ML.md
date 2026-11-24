# Trained machine-learning model

Code: `backend/matchedge/ml/` (`features.py`, `train.py`, `predict.py`). Page: **Model lab**.
Library: scikit-learn (free, open source). Everything trains and runs on your computer.

## What it predicts

Match result (home/draw/away), Over 2.5 goals and both teams to score, for domestic-league fixtures
in the 22 football-data.co.uk divisions. All other goal markets (Over 1.5/3.5, team goals, double
chance, draw no bet, Asian handicaps, first half) are derived consistently: the expected goals
(λ_home, λ_away) are re-fitted so the Poisson score matrix reproduces the ML's home-minus-away and
Over 2.5 probabilities. UEFA and cup fixtures, and corners/cards, keep the statistical engine.

## Features (walk-forward — no look-ahead)

Matches are processed in date order; each match's features come only from earlier matches
(`tests/test_ml.py::test_features_never_see_the_match_or_the_future` proves this):

* Elo ratings (one pool per country across divisions, home advantage 65, goal-difference multiplier,
  20 % regression toward the league mean at a new season, newcomers start below their new league);
* exponentially weighted averages of goals, shots, shots on target, corners and cards for/against,
  overall and home/away; recent-form points; season points per game; rest days;
* league scoring level, attack/defence relative to the league, form-based expected goals;
* the statistical engine's own probabilities and expected goals (stacking);
* optional market group: Bet365 pre-match 1X2 and Over/Under 2.5 with the margin removed, and the
  main Asian handicap line.

Missing statistics are skipped, never counted as zero; the trees handle missing values natively.

## Models and validation

Gradient-boosted trees (`HistGradientBoostingClassifier`, early stopping) in two variants:
**stats** (no odds) and **market** (with Bet365 prices; used only when the fixture has them).

Walk-forward: for each test season (the three latest completed seasons) the models are trained only
on earlier seasons, then scored on the test season against the statistical engine and Bet365's
margin-free probabilities on exactly the same matches. First run (22,388 test matches, 2023/24–2025/26):

| | Match result: log loss / accuracy | Over 2.5 | BTTS |
|---|---|---|---|
| Statistical engine | 1.0255 / 48.8 % | 0.6869 / 55.0 % | 0.6887 / 53.9 % |
| ML — statistics only | 1.0161 / 49.2 % | 0.6835 / 55.6 % | 0.6877 / 54.1 % |
| ML — statistics + Bet365 odds | 1.0015 / 50.6 % | 0.6787 / 56.8 % | 0.6865 / 54.6 % |
| Bet365's own odds | 1.0002 / 50.6 % | 0.6775 / 56.8 % | — |

Reading it: the ML is clearly more accurate than the statistical engine and well calibrated, and with
Bet365's prices it matches the bookmaker — but does not beat it. Value-betting simulations (bet when
model probability × Bet365 pre-match odds − 1 exceeds 2/5/10 %) lost money in every test season
(best: ML with odds, about −5 %), so the model does not find mispriced odds.

Weekend-plan backtest on the same unseen seasons (out-of-sample ML predictions only): selected legs won
71.5 % vs 71.1 % predicted (the statistical engine: 63 % vs 70 %), singles +1.2 %, CLV +0.3 %; tickets
+17 % over 86 tickets — within the ±35 % that luck alone produces at those odds, so not evidence of
profit. The improvement that is solid: the probabilities now mean what they say.

## Using it

* **Model lab → Train model** (1–2 minutes) or `python -m matchedge train`. Retrain after imports so
  the newest matches are included. The final model is trained on every season and saved to
  `data/models/matchedge_ml.joblib` (git-ignored).
* Setting `prediction_engine`: `auto` (default) uses the ML per market only where it beat the
  statistical engine out of sample; `statistical` never uses it. Without a trained model the app
  behaves exactly as before.
* Each match page's Model tab shows the ML and statistical-engine probabilities side by side; the
  uncertainty range is the gap between them (at least ±2 points).
* Historical performance → Profit backtest → "ML model" replays the weekend plan with the saved
  out-of-sample predictions.

## Limits

No football model can make results predictable: the bookmaker itself picks the right 1X2 outcome
about half the time. Free data has no lineups, injuries, xG history or tracking data — the inputs that
professional models add. Treat the ML as the most accurate probability available to this app, not as
an edge over the market.
