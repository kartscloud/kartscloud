# kalshi_nba_bets.py — Kalshi NBA probability & best-bet finder

Finds **every Kalshi market for an NBA matchup** (default: Spurs vs Knicks),
quantifies all of them, and surfaces the **best value bets** — broken down by
**period** (each quarter Q1–Q4, halves, full game, series) and by **player across
every metric** (points, rebounds, assists, threes, steals, blocks, free throws,
double/triple-doubles, leaders, winners, spreads, totals).

Pure Python 3 stdlib — no `pip install`, no API key (Kalshi market reads are public).

## Quick start

```bash
python3 scripts/kalshi_nba_bets.py                 # top value bets (auto fair value)
python3 scripts/kalshi_nba_bets.py --by-period     # every quarter / half, market by market
python3 scripts/kalshi_nba_bets.py --by-player     # every player, every metric
python3 scripts/kalshi_nba_bets.py --all --csv all.csv --json all.json   # everything + export
python3 scripts/kalshi_nba_bets.py --teams "Celtics,Lakers" --abbr "BOS,LAL"
python3 scripts/kalshi_nba_bets.py --model scripts/projections.example.json  # add your own edges
```

Useful flags: `--top N` (rows in best-bets table), `--min-edge 0.04` (min edge to list).

### Visual report (Kalshi vs Here)

`report.py` renders graphs + a short markdown report comparing Kalshi's implied
probability to this tool's fair value, into `scripts/report/`. Needs matplotlib.

```bash
pip install matplotlib
python3 scripts/report.py --top 20 --min-edge 0.05
```

Produces `top_bets.png` (implied vs fair bars), `scatter.png` (every market's
mispricing), `quarter_totals.png` (per-quarter ladders: dots = Kalshi, lines =
fitted fair), and `README.md` with a per-bet table + summary stats.

## Two layers of quantification

1. **Implied probability** — a Kalshi YES contract at 62c implies ~62% and costs
   $0.62 to win $1. Listing markets already "finds every probability".

2. **Fair value + edge (automatic, no input needed)** — the price can't tell you a
   bet is *good* by itself, so the script builds a reference from the market's own data:
   - **Strike ladders** (a player's 10+/15+/20+/25+ points, a quarter's
     Over 45.5/48.5/51.5… total) are fit to a normal distribution. The smooth
     fitted curve is the consensus fair value; strikes that deviate are flagged as
     value with `edge = fair − implied` and **EV per $1 contract**.
   - **Multi-outcome markets** (winner: Spurs/Knicks/Tie; leaders) are **de-vigged** —
     prices normalized to sum to 100% to strip the house margin.
   - `--model projections.json` lets you override/extend fair values with your own
     numbers (see `projections.example.json`).

Output columns: `EDGE`, `EV/$1`, side (YES/NO), `IMPLIED`, `FAIR`, and a
`[period/metric]` tag plus the market title.

## Honest limits

- Returns only what Kalshi actually lists. For the 2026 Finals it found rich
  per-quarter and per-player markets; many regular games only have game-level lines.
- Substring matching can mislabel look-alikes — sanity-check `IMPLIED`/`FAIR`.
- The normal-ladder fit and de-vig are approximations; "fair" reflects the market's
  own consensus, not inside information. A flagged edge often means *thin/stale
  pricing on one strike*, not a guaranteed win.
- Analysis tool, not betting advice. Markets move — re-run before acting.
