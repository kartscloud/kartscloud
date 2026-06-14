#!/usr/bin/env python3
"""
kalshi_nba_bets.py
==================

Find EVERY Kalshi market for an NBA matchup (default: Spurs vs Knicks),
quantify every one of them, and surface the best value bets -- broken down by
period (each quarter, each half, full game, series) and by player across every
metric Kalshi lists (points, rebounds, assists, threes, steals, blocks,
free throws, double/triple-doubles, leaders, winners, spreads, totals).

Two layers of quantification
----------------------------
1. IMPLIED PROBABILITY -- on Kalshi a binary market's price *is* its probability
   (a YES contract at 62c implies ~62% and costs $0.62 to win $1). So listing the
   markets already "finds every probability".

2. FAIR VALUE + EDGE (automatic, no manual input) -- the price alone can't tell
   you a bet is "good"; you need a reference. This script builds one from the
   market's OWN data:
     * STRIKE LADDERS (e.g. a player's 10+/15+/20+/25+ points, or a quarter's
       Over 45.5/48.5/51.5... total) are fit to a normal distribution. The fitted
       smooth curve is the consensus fair value; strikes whose price deviates from
       it are flagged as value (edge = fair - implied), with EV per $1 contract.
     * MULTI-OUTCOME MARKETS (winners: Spurs/Knicks/Tie; leaders: each player) are
       de-vigged -- prices normalized to sum to 100% -- to remove the house margin
       and reveal the true implied probability of each outcome.
   You can still override/extend the fair values with your own projections via
   --model projections.json (see projections.example.json).

Honest limits: the script only returns markets Kalshi actually lists, substring
matching can mislabel look-alikes (sanity-check the columns), and the normal-ladder
fit is an approximation. This is analysis, not betting advice.

Usage
-----
    python3 scripts/kalshi_nba_bets.py                      # best bets, auto fair value
    python3 scripts/kalshi_nba_bets.py --by-period          # grouped quarter-by-quarter
    python3 scripts/kalshi_nba_bets.py --by-player          # grouped player-by-player
    python3 scripts/kalshi_nba_bets.py --all --csv all.csv  # dump every market + metrics
    python3 scripts/kalshi_nba_bets.py --teams "Celtics,Lakers" --abbr "BOS,LAL"
    python3 scripts/kalshi_nba_bets.py --model scripts/projections.example.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Optional

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _get(path: str, params: dict, retries: int = 4) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{KALSHI_BASE}{path}?{qs}"
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise SystemExit(
        f"\nCould not reach Kalshi ({url}): {last_err}\n"
        "If you're offline/sandboxed, run this on a machine with internet access. "
        "Kalshi market endpoints are public (no key needed)."
    )


def fetch_open_events(team_keywords: list[str]) -> list[dict]:
    """Page through open events (with nested markets); keep those whose
    title/sub-title/ticker mention any team keyword (word-boundary matched so
    'SAS' doesn't match 'kanSAS')."""
    patterns = [re.compile(rf"\b{re.escape(k)}\b", re.I) for k in team_keywords]
    matched, cursor, pages = [], None, 0
    while True:
        data = _get("/events", {"limit": 200, "status": "open",
                                "with_nested_markets": "true", "cursor": cursor})
        for ev in data.get("events", []):
            hay = " ".join(str(ev.get(f, "")) for f in
                           ("title", "sub_title", "event_ticker", "series_ticker"))
            if any(p.search(hay) for p in patterns):
                matched.append(ev)
        cursor = data.get("cursor")
        pages += 1
        if not cursor or pages > 100:
            break
    return matched


# --------------------------------------------------------------------------- #
# Price / stats helpers
# --------------------------------------------------------------------------- #
def _price(mkt: dict, key: str) -> Optional[float]:
    """Price as a probability in [0,1]. Handles new '*_dollars' floats and old
    integer-cent fields."""
    v = mkt.get(f"{key}_dollars")
    if v is not None:
        return float(v)
    v = mkt.get(key)
    return float(v) / 100.0 if v is not None else None


def _size(mkt: dict, key: str) -> Optional[float]:
    for k in (f"{key}_fp", key):
        v = mkt.get(k)
        if v is not None:
            return float(v)
    return None


def implied_prob(mkt: dict) -> Optional[float]:
    yb, ya = _price(mkt, "yes_bid"), _price(mkt, "yes_ask")
    if yb is not None and ya is not None and (yb > 0 or ya > 0):
        return (yb + ya) / 2.0
    last = _price(mkt, "last_price")
    if last:
        return last
    nb, na = _price(mkt, "no_bid"), _price(mkt, "no_ask")
    if nb is not None and na is not None and (nb > 0 or na > 0):
        return 1.0 - (nb + na) / 2.0
    return None


def normal_cdf(x: float, mean: float, sd: float) -> float:
    if sd <= 0:
        return 1.0 if x >= mean else 0.0
    return 0.5 * (1.0 + math.erf((x - mean) / (sd * math.sqrt(2.0))))


def inv_normal_cdf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation)."""
    p = min(max(p, 1e-9), 1 - 1e-9)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def prob_at_least(threshold: float, mean: float, sd: float) -> float:
    return 1.0 - normal_cdf(threshold - 0.5, mean, sd)


def parse_threshold(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+", text)
    if m:
        return float(m.group(1))
    m = re.search(r"(?:over|at least|more than|>=?|above)\s*(\d+(?:\.\d+)?)", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
PERIODS = [
    (r"\b(1st quarter|1q)\b", "Q1"), (r"\b(2nd quarter|2q)\b", "Q2"),
    (r"\b(3rd quarter|3q)\b", "Q3"), (r"\b(4th quarter|4q)\b", "Q4"),
    (r"\b(first half|1h)\b", "H1"), (r"\b(second half|2h)\b", "H2"),
    (r"\bseries\b", "Series"),
]
METRICS = [
    (r"three|3pt|3-point", "threes"), (r"rebound", "rebounds"),
    (r"assist", "assists"), (r"steal", "steals"), (r"block", "blocks"),
    (r"free throw", "free_throws"), (r"triple double|triple-double", "triple_double"),
    (r"double double|double-double", "double_double"), (r"\bspread\b", "spread"),
    (r"winner|\bwin\b", "winner"), (r"leader|most points|most rebound|most assist", "leader"),
    (r"total|points scored", "total"), (r"\bpoints\b|\bpts\b", "points"),
]
PLAYER_RE = re.compile(r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+)+)\s*:")


def classify(title: str, subtitle: str) -> tuple[str, str, Optional[str]]:
    text = f"{title} {subtitle}".lower()
    period = next((p for rx, p in PERIODS if re.search(rx, text)), "Game")
    metric = next((m for rx, m in METRICS if re.search(rx, text)), "other")
    player = None
    for src in (subtitle, title):
        m = PLAYER_RE.search(src or "")
        if m:
            cand = m.group(1).strip()
            if cand.lower() not in ("new york", "san antonio"):
                player = cand
                break
    return period, metric, player


# --------------------------------------------------------------------------- #
# Row + evaluation
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    event: str
    period: str
    metric: str
    player: Optional[str]
    threshold: Optional[float]
    implied: Optional[float]
    fair: Optional[float] = None
    fair_src: Optional[str] = None      # "ladder-fit" | "de-vig" | "model"
    side: Optional[str] = None
    edge: Optional[float] = None
    ev: Optional[float] = None
    yes_ask: Optional[float] = None
    no_ask: Optional[float] = None
    spread: Optional[float] = None      # ask-bid (liquidity quality)
    volume: Optional[float] = None
    open_interest: Optional[float] = None
    ticker: str = ""
    title: str = ""
    subtitle: str = ""
    event_ticker: str = ""


def build_row(mkt: dict, event_title: str) -> Row:
    title = mkt.get("title", "")
    subtitle = mkt.get("yes_sub_title", "") or mkt.get("subtitle", "")
    period, metric, player = classify(title, subtitle)
    yb, ya = _price(mkt, "yes_bid"), _price(mkt, "yes_ask")
    return Row(
        event=event_title, period=period, metric=metric, player=player,
        threshold=parse_threshold(f"{title} {subtitle}"),
        implied=implied_prob(mkt),
        yes_ask=ya, no_ask=_price(mkt, "no_ask"),
        spread=(ya - yb) if (ya is not None and yb is not None) else None,
        volume=_size(mkt, "volume"), open_interest=_size(mkt, "open_interest"),
        ticker=mkt.get("ticker", ""), title=title, subtitle=subtitle,
        event_ticker=mkt.get("event_ticker", ""),
    )


def fit_ladder(rows: list[Row]) -> None:
    """Fit a normal to (threshold, P(over)) points and set fair/fair_src per row."""
    pts = [(r.threshold, r.implied) for r in rows
           if r.threshold is not None and r.implied is not None and 0 < r.implied < 1]
    if len({t for t, _ in pts}) < 3:
        return
    xs = [t - 0.5 for t, _ in pts]                # continuity-corrected strike
    zs = [inv_normal_cdf(1 - p) for _, p in pts]  # P(over)=1-CDF(x) -> z for x
    n = len(zs)
    mz, mx = sum(zs) / n, sum(xs) / n
    var = sum((z - mz) ** 2 for z in zs)
    if var <= 1e-9:
        return
    sd = sum((z - mz) * (x - mx) for z, x in zip(zs, xs)) / var
    mean = mx - sd * mz
    if sd <= 0:
        return
    for r in rows:
        if r.threshold is not None:
            r.fair = prob_at_least(r.threshold, mean, sd)
            r.fair_src = "ladder-fit"


def devig(rows: list[Row]) -> None:
    """Normalize implied probs of mutually-exclusive outcomes to sum to 1.
    Only valid for true partitions, so require the raw sum to look like one
    (~1.0 plus vig). Independent yes/no markets sum far above 1 and are skipped."""
    valid = [r for r in rows if r.implied is not None]
    s = sum(r.implied for r in valid)
    if len(valid) < 2 or not (0.85 <= s <= 1.6):
        return
    for r in valid:
        r.fair = r.implied / s
        r.fair_src = "de-vig"


def apply_model(rows: list[Row], model: dict) -> None:
    for r in rows:
        text = f"{r.title} {r.subtitle}".lower()
        for m in model.get("matchers", []):
            need = [c.lower() for c in m.get("contains", [])]
            ban = [c.lower() for c in m.get("exclude", [])]
            if not need or not all(n in text for n in need) or any(b in text for b in ban):
                continue
            if m.get("type") == "prob":
                r.fair, r.fair_src = float(m["yes"]), "model"
            elif m.get("type") == "normal":
                thr = m.get("threshold", r.threshold)
                if thr is not None:
                    r.fair = prob_at_least(float(thr), float(m["mean"]), float(m["sd"]))
                    r.fair_src = "model"
            break


def score_edges(rows: list[Row]) -> None:
    """Pick the +EV side and compute edge/EV from fair vs ask (dollars)."""
    for r in rows:
        if r.fair is None or r.implied is None:
            continue
        cands = []
        if r.yes_ask and r.yes_ask > 0:
            cands.append(("YES", r.fair - r.yes_ask, r.fair - r.implied))
        if r.no_ask and r.no_ask > 0:
            cands.append(("NO", (1 - r.fair) - r.no_ask, r.implied - r.fair))
        if not cands:
            continue
        r.side, r.ev, r.edge = max(cands, key=lambda c: c[1])


# Cumulative "X+ / Over X" metrics whose strike ladder fits a normal.
LADDER_METRICS = {"points", "rebounds", "assists", "threes", "steals",
                  "blocks", "free_throws", "total"}
# Mutually-exclusive outcome metrics suitable for de-vigging.
PARTITION_METRICS = {"winner", "leader"}


def analyze(rows: list[Row], model: Optional[dict]) -> None:
    # Group by (event_ticker, player) so each player's ladder/outcomes are separate.
    groups: dict[tuple, list[Row]] = defaultdict(list)
    for r in rows:
        groups[(r.event_ticker, r.player)].append(r)
    for grp in groups.values():
        metric = grp[0].metric
        distinct = {r.threshold for r in grp if r.threshold is not None}
        if metric in LADDER_METRICS and len(distinct) >= 3:
            fit_ladder(grp)
        elif metric in PARTITION_METRICS and len(grp) >= 2 and len(distinct) <= 1:
            devig(grp)   # winner / leader outcomes
    if model:
        apply_model(rows, model)         # model overrides auto fair where it matches
    score_edges(rows)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def pct(x: Optional[float]) -> str:
    return f"{x*100:5.1f}%" if x is not None else "  -  "


def fmt_bet(r: Row) -> str:
    tag = f"[{r.period}/{r.metric}]"
    who = f"{r.player} " if r.player else ""
    return (f"{pct(r.edge):>6}  {(f'{r.ev:+.2f}' if r.ev is not None else '  -  '):>6}  "
            f"{(r.side or '-'):>3}  impl {pct(r.implied)}  fair {pct(r.fair)}  "
            f"{tag:<18} {who}{r.title} {('· '+r.subtitle) if r.subtitle else ''}")


def print_best_bets(rows: list[Row], top: int, min_edge: float) -> None:
    bets = [r for r in rows if r.ev is not None and (r.edge or 0) >= min_edge]
    bets.sort(key=lambda r: r.ev, reverse=True)
    print(f"\n=== TOP {min(top, len(bets))} VALUE BETS (edge >= {min_edge*100:.0f}%) ===")
    print(f"{'EDGE':>6}  {'EV/$1':>6}  {'SD':>3}  {'IMPLIED':>10}  {'FAIR':>10}  MARKET")
    print("-" * 110)
    for r in bets[:top]:
        print(fmt_bet(r))
    if not bets:
        print("(no +EV markets cleared the edge threshold)")
    print()


def print_by(rows: list[Row], key: str) -> None:
    label = "PERIOD" if key == "period" else "PLAYER"
    buckets: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        k = (r.player or "— team/game —") if key == "player" else r.period
        buckets[k].append(r)
    order = (["Q1", "Q2", "Q3", "Q4", "H1", "H2", "Game", "Series"]
             if key == "period" else sorted(buckets))
    for k in order:
        if k not in buckets:
            continue
        grp = sorted(buckets[k], key=lambda r: (r.ev if r.ev is not None else -9))
        priced = [r for r in grp if r.implied is not None]
        print(f"\n### {label}: {k}  ({len(priced)} priced markets)")
        for r in sorted(priced, key=lambda r: -(r.implied or 0)):
            ev = f"EV {r.ev:+.2f}" if r.ev is not None else ""
            print(f"  {pct(r.implied)} impl | fair {pct(r.fair)} {ev:>8} "
                  f"[{r.metric}] {r.title} · {r.subtitle}")
    print()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Kalshi NBA probabilities & best bets.")
    ap.add_argument("--teams", default="Spurs,Knicks")
    ap.add_argument("--abbr", default="SAS,NYK")
    ap.add_argument("--model", help="projections JSON to override/extend auto fair value")
    ap.add_argument("--min-edge", type=float, default=0.05)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--by-period", action="store_true", help="group output by quarter/half")
    ap.add_argument("--by-player", action="store_true", help="group output by player")
    ap.add_argument("--all", action="store_true", help="show best bets AND full breakdowns")
    ap.add_argument("--csv")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    keywords = [t.strip() for t in (args.teams + "," + args.abbr).split(",") if t.strip()]
    model = json.load(open(args.model)) if args.model else None

    print(f"Searching Kalshi for: {', '.join(keywords)} ...", file=sys.stderr)
    events = fetch_open_events(keywords)
    rows = [build_row(m, ev.get("title", ev.get("event_ticker", "")))
            for ev in events for m in ev.get("markets", [])]
    print(f"Matched {len(events)} events, {len(rows)} markets "
          f"({sum(1 for r in rows if r.implied is not None)} priced).", file=sys.stderr)

    analyze(rows, model)

    if args.by_period or args.all:
        print_by(rows, "period")
    if args.by_player or args.all:
        print_by(rows, "player")
    if not (args.by_period or args.by_player) or args.all:
        print_best_bets(rows, args.top, args.min_edge)

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()) if rows else [])
            w.writeheader()
            for r in rows:
                w.writerow(asdict(r))
        print(f"Wrote {args.csv}", file=sys.stderr)
    if args.json:
        json.dump([asdict(r) for r in rows], open(args.json, "w"), indent=2)
        print(f"Wrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
