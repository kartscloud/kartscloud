#!/usr/bin/env python3
"""
kalshi_nba_bets.py
==================

Pull EVERY market Kalshi lists for a given NBA matchup (default: Spurs vs Knicks),
turn each market's price into an implied probability, and -- if you feed it your
own projections -- rank the best value bets by edge / expected value.

Why it works this way
---------------------
* On Kalshi a binary market's YES price (in cents) *is* the market's implied
  probability. A YES contract trading at 62c implies ~62% and costs $0.62 to win
  $1.00. So "find every probability" == "list every Kalshi market for the game
  and read its price". This script does that with zero dependencies (stdlib only).

* "Best bets" is NOT something a price feed alone can tell you -- the price is
  already the consensus probability. A bet is only "good" if YOUR estimate of the
  true probability differs from Kalshi's price (that gap is your edge). So to get
  ranked best bets you pass --model projections.json with your own numbers; the
  script computes edge = your_prob - implied_prob and EV per $1 contract, then
  sorts. Without a model it just dumps every market + implied probability.

Honest coverage note
--------------------
Kalshi's NBA coverage is mostly game-level (moneyline, spread, total, sometimes
series). Granular per-player and per-quarter props mostly live on sportsbooks
(DK/FD), not Kalshi. This script returns everything Kalshi actually lists -- it
can't invent markets that don't exist. Any per-player/per-quarter markets Kalshi
*does* offer will be picked up automatically by the keyword filter.

Usage
-----
    # List every Spurs/Knicks market with implied probabilities:
    python3 scripts/kalshi_nba_bets.py

    # Different game:
    python3 scripts/kalshi_nba_bets.py --teams "Celtics,Lakers" --abbr "BOS,LAL"

    # Rank best bets against your own projections, write CSV + JSON:
    python3 scripts/kalshi_nba_bets.py --model projections.example.json \
        --csv out.csv --json out.json --min-edge 0.04

See projections.example.json (written alongside this script) for the model format.
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
from dataclasses import dataclass, field, asdict
from typing import Iterable, Optional

# Kalshi public Trade API v2. Reading market data needs no auth/login.
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _get(path: str, params: dict, retries: int = 4) -> dict:
    """GET a Kalshi endpoint with simple exponential backoff."""
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
        "If you're in a sandboxed/offline environment, run this script on a machine "
        "with internet access. The Kalshi market endpoints are public (no key needed)."
    )


def fetch_open_events(team_keywords: list[str]) -> list[dict]:
    """
    Page through all open Kalshi events (with nested markets) and keep the ones
    whose title/sub-title/ticker mentions any of our team keywords.
    """
    # Word-boundary patterns so short abbreviations (SAS, NYK) don't match
    # substrings like "kanSAS" or "arkanSAS".
    patterns = [re.compile(rf"\b{re.escape(k)}\b", re.I) for k in team_keywords]
    matched: list[dict] = []
    cursor: Optional[str] = None
    pages = 0
    while True:
        data = _get(
            "/events",
            {
                "limit": 200,
                "status": "open",
                "with_nested_markets": "true",
                "cursor": cursor,
            },
        )
        for ev in data.get("events", []):
            haystack = " ".join(
                str(ev.get(f, "")) for f in ("title", "sub_title", "event_ticker", "series_ticker")
            )
            if any(p.search(haystack) for p in patterns):
                matched.append(ev)
        cursor = data.get("cursor")
        pages += 1
        if not cursor or pages > 100:
            break
    return matched


# --------------------------------------------------------------------------- #
# Probability helpers
# --------------------------------------------------------------------------- #
def _price(mkt: dict, key: str) -> Optional[float]:
    """
    Read a Kalshi price as a probability in [0,1].

    Kalshi's current API returns dollar-denominated floats (e.g. yes_ask_dollars
    = 0.45 means 45c / 45%). Older payloads used integer cents (yes_ask = 45).
    Handle both. `key` is the base name, e.g. 'yes_ask'.
    """
    v = mkt.get(f"{key}_dollars")
    if v is not None:
        return float(v)
    v = mkt.get(key)
    if v is not None:
        return float(v) / 100.0
    return None


def _size(mkt: dict, key: str) -> Optional[float]:
    """Read a volume/open-interest figure across old and new field names."""
    for k in (f"{key}_fp", key):
        v = mkt.get(k)
        if v is not None:
            return float(v)
    return None


def implied_prob(mkt: dict) -> Optional[float]:
    """
    Implied YES probability in [0,1].
    Prefer the mid of yes_bid/yes_ask; fall back to last_price; then the NO side.
    A 0/0 quote (no real market) is treated as unpriced.
    """
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


def prob_at_least(threshold: float, mean: float, sd: float) -> float:
    """P(X >= threshold) under a normal approximation (continuity-corrected)."""
    return 1.0 - normal_cdf(threshold - 0.5, mean, sd)


def parse_threshold(text: str) -> Optional[float]:
    """
    Best-effort: pull the numeric line out of a market title/subtitle, e.g.
    'Over 24.5', '25+', 'at least 110', 'more than 7.5 threes'.
    """
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+", text)
    if m:
        return float(m.group(1))
    m = re.search(r"(?:over|at least|more than|>=?|above)\s*(\d+(?:\.\d+)?)", text, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# Model / edge
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    event: str
    ticker: str
    title: str
    subtitle: str
    implied: Optional[float]
    yes_ask: Optional[float]   # dollars, 0-1
    no_ask: Optional[float]    # dollars, 0-1
    volume: Optional[float]
    open_interest: Optional[float]
    close_time: Optional[str]
    fair: Optional[float] = None
    side: Optional[str] = None          # "YES" or "NO"
    edge: Optional[float] = None        # fair - price for the chosen side
    ev_per_contract: Optional[float] = None
    matcher: Optional[str] = None


def fair_from_model(mkt: dict, model: dict) -> tuple[Optional[float], Optional[str]]:
    """
    Match a market against user projections and return (fair_yes_prob, matcher_label).

    Each matcher in model["matchers"] is:
      {"contains": ["wembanyama","points"], "type":"normal", "mean":24.5, "sd":7.0}
    or a direct probability:
      {"contains": ["spurs","win"], "type":"prob", "yes": 0.47}
    The threshold for 'normal' matchers is parsed from the market text unless
    overridden with "threshold".
    """
    text = f"{mkt.get('title','')} {mkt.get('yes_sub_title','')} {mkt.get('subtitle','')}".lower()
    for m in model.get("matchers", []):
        needles = [c.lower() for c in m.get("contains", [])]
        bans = [c.lower() for c in m.get("exclude", [])]
        if not needles or not all(n in text for n in needles):
            continue
        if any(b in text for b in bans):
            continue
        label = " & ".join(m.get("contains", []))
        if m.get("type") == "prob":
            return float(m["yes"]), label
        if m.get("type") == "normal":
            thr = m.get("threshold")
            if thr is None:
                thr = parse_threshold(text)
            if thr is None:
                continue
            return prob_at_least(float(thr), float(m["mean"]), float(m["sd"])), label
    return None, None


def evaluate(mkt: dict, event_title: str, model: Optional[dict]) -> Row:
    imp = implied_prob(mkt)
    yes_ask = _price(mkt, "yes_ask")
    no_ask = _price(mkt, "no_ask")
    row = Row(
        event=event_title,
        ticker=mkt.get("ticker", ""),
        title=mkt.get("title", ""),
        subtitle=mkt.get("yes_sub_title", "") or mkt.get("subtitle", ""),
        implied=imp,
        yes_ask=yes_ask,
        no_ask=no_ask,
        volume=_size(mkt, "volume"),
        open_interest=_size(mkt, "open_interest"),
        close_time=mkt.get("close_time"),
    )
    if model is None or imp is None:
        return row

    fair, label = fair_from_model(mkt, model)
    if fair is None:
        return row
    row.fair = fair
    row.matcher = label

    # Compare buying YES at the ask vs buying NO at the ask; pick the +EV side.
    # Costs are already in dollars (0-1). Skip 0-priced/empty quotes.
    candidates = []
    if yes_ask and yes_ask > 0:
        candidates.append(("YES", fair - yes_ask, fair))         # ev, prob-win
    if no_ask and no_ask > 0:
        candidates.append(("NO", (1 - fair) - no_ask, 1 - fair))
    if not candidates:
        return row
    side, ev, _ = max(candidates, key=lambda c: c[1])
    row.side = side
    row.ev_per_contract = ev
    row.edge = (fair - imp) if side == "YES" else (imp - fair)
    return row


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def pct(x: Optional[float]) -> str:
    return f"{x*100:5.1f}%" if x is not None else "  -  "


def print_table(rows: list[Row], has_model: bool) -> None:
    if not rows:
        print("\nNo Kalshi markets matched. Either the game isn't listed yet, "
              "or try different --teams/--abbr keywords.\n")
        return
    print()
    if has_model:
        print(f"{'EDGE':>6}  {'EV/$1':>6}  {'SIDE':>4}  {'IMPL':>6}  {'FAIR':>6}  TITLE")
        print("-" * 100)
        for r in rows:
            print(f"{pct(r.edge):>6}  "
                  f"{(f'{r.ev_per_contract:+.2f}' if r.ev_per_contract is not None else '  -  '):>6}  "
                  f"{(r.side or '-'):>4}  {pct(r.implied):>6}  {pct(r.fair):>6}  "
                  f"{r.title} {('· '+r.subtitle) if r.subtitle else ''}")
    else:
        print(f"{'IMPL':>6}  {'YES_ASK':>7}  {'VOL':>9}  TITLE")
        print("-" * 100)
        for r in rows:
            ask = f"{r.yes_ask*100:5.0f}c" if r.yes_ask is not None else "  -  "
            vol = f"{r.volume:,.0f}" if r.volume is not None else "-"
            print(f"{pct(r.implied):>6}  {ask:>7}  {vol:>9}  "
                  f"{r.title} {('· '+r.subtitle) if r.subtitle else ''}")
    print()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Find Kalshi NBA market probabilities & best bets.")
    ap.add_argument("--teams", default="Spurs,Knicks",
                    help="Comma-separated team name keywords (default: Spurs,Knicks)")
    ap.add_argument("--abbr", default="SAS,NYK",
                    help="Comma-separated team abbreviations to also match (default: SAS,NYK)")
    ap.add_argument("--model", help="Path to projections JSON to rank best bets by edge/EV")
    ap.add_argument("--min-edge", type=float, default=0.0,
                    help="Only show bets with edge >= this (e.g. 0.04 = 4%%). Needs --model.")
    ap.add_argument("--csv", help="Write results to this CSV path")
    ap.add_argument("--json", help="Write results to this JSON path")
    args = ap.parse_args(argv)

    keywords = [t.strip() for t in (args.teams + "," + args.abbr).split(",") if t.strip()]
    model = None
    if args.model:
        with open(args.model) as f:
            model = json.load(f)

    print(f"Searching Kalshi open markets for: {', '.join(keywords)} ...", file=sys.stderr)
    events = fetch_open_events(keywords)
    print(f"Matched {len(events)} event(s).", file=sys.stderr)

    rows: list[Row] = []
    for ev in events:
        title = ev.get("title", ev.get("event_ticker", ""))
        for mkt in ev.get("markets", []):
            rows.append(evaluate(mkt, title, model))

    if model is not None:
        # Best bets first: sort by EV (then edge), drop non-evaluated / below threshold.
        graded = [r for r in rows if r.ev_per_contract is not None and (r.edge or 0) >= args.min_edge]
        graded.sort(key=lambda r: (r.ev_per_contract or 0), reverse=True)
        ungraded = [r for r in rows if r.ev_per_contract is None]
        print_table(graded, has_model=True)
        if ungraded:
            print(f"({len(ungraded)} market(s) had no matching projection — not ranked.)\n",
                  file=sys.stderr)
        out_rows = graded + ungraded
    else:
        rows.sort(key=lambda r: (r.implied if r.implied is not None else -1), reverse=True)
        print_table(rows, has_model=False)
        out_rows = rows

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(Row("", "", "", "", None, None, None,
                                                              None, None, None)).keys()))
            w.writeheader()
            for r in out_rows:
                w.writerow(asdict(r))
        print(f"Wrote {args.csv}", file=sys.stderr)
    if args.json:
        with open(args.json, "w") as f:
            json.dump([asdict(r) for r in out_rows], f, indent=2)
        print(f"Wrote {args.json}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
