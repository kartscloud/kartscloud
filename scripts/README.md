# kalshi_nba_bets.py — Kalshi NBA probability & best-bet finder

Pulls **every market Kalshi lists for a given NBA matchup** (default: Spurs vs
Knicks), converts each market's price into an implied probability, and — when you
supply your own projections — ranks the **best value bets** by edge and expected
value (EV).

Pure Python 3 standard library. No `pip install`, no API key (Kalshi's market
read endpoints are public).

## Quick start

```bash
# Every Spurs/Knicks market + implied probability, sorted high→low:
python3 scripts/kalshi_nba_bets.py

# A different game:
python3 scripts/kalshi_nba_bets.py --teams "Celtics,Lakers" --abbr "BOS,LAL"

# Rank best bets vs your own projections; only show >=4% edge; save CSV+JSON:
python3 scripts/kalshi_nba_bets.py \
  --model scripts/projections.example.json \
  --min-edge 0.04 --csv bets.csv --json bets.json
```

## How to read it

- **Kalshi's price IS the implied probability.** A YES contract at 62c implies
  ~62% and costs $0.62 to win $1.00. Listing markets = "finding every probability".
- **A bet is only "best" relative to a better estimate.** The price is already the
  market's consensus, so the script can't conjure an edge from the price alone.
  Feed it `--model projections.json` with *your* numbers; it computes
  `edge = your_prob − implied_prob` and `EV per $1 contract`, then sorts.
  Without `--model` it just lists every market and its implied probability.

## Projections format

See `projections.example.json`. Each matcher targets markets whose
title+subtitle contain **all** `contains` strings (and **none** of `exclude`):

```jsonc
// player/quarter stat → P(value ≥ threshold) under a normal model.
// threshold is auto-parsed from the market ("24.5", "10+") unless you set it.
{ "contains": ["wembanyama","points"], "exclude":["series","leader"],
  "type": "normal", "mean": 24.0, "sd": 8.0 }

// a binary market → direct probability.
{ "contains": ["1st quarter winner","spurs"], "type": "prob", "yes": 0.60 }
```

## Honest limitations

- **Coverage:** the script returns only what Kalshi actually lists. For the 2026
  Finals it found rich per-quarter (totals/spreads/winners) and per-player
  (points/rebounds/assists/threes/steals/blocks) markets — but for many regular
  games Kalshi only offers game-level lines. Deep player props live on
  sportsbooks (DK/FD), not Kalshi.
- **Matching is substring-based**, so sanity-check the `FAIR`/`IMPL` columns; use
  `exclude` to dodge look-alikes (e.g. series-long "every game" parlays).
- **The normal-distribution model is a rough approximation.** Your edge is only as
  good as the `mean`/`sd` you feed it. Garbage in, garbage out.
- This is an analysis tool, not betting advice. Markets move; re-run before acting.
