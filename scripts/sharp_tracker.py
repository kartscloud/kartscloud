#!/usr/bin/env python3
"""
sharp_tracker.py -- "smart money" tracker for Kalshi sports markets.

IMPORTANT: Kalshi trade data is ANONYMOUS. The public API exposes each trade's
size, price, taker side and a block-trade flag, but NO account or user identity.
There is no public leaderboard and no way to follow a specific bettor. So this
does not (cannot) track named people -- it tracks the *sharp action* itself:
large prints, block trades, aggressive taker-flow imbalance, and the price moves
that result. That is the standard proxy for "where the smart money is going".

What it reports per market (within --hours window):
  vol        total contracts traded
  net flow   aggressive YES notional minus aggressive NO notional ($)
             -> sign = direction the takers are leaning
  big        # trades >= --min-size contracts
  block      # block trades (negotiated size, often institutional/sharp)
  move       price change over the window (first -> last trade), in cents
  signal     composite score; higher = more notable sharp activity

Usage
-----
    python3 scripts/sharp_tracker.py                       # snapshot, top signals
    python3 scripts/sharp_tracker.py --hours 6 --top 15
    python3 scripts/sharp_tracker.py --alerts              # only NEW big/block prints
                                                           # (for scheduled monitoring)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

import kalshi_nba_bets as K

SEEN_FILE = "/tmp/kalshi_sharp_seen.json"


def get(path: str, params: dict, retries: int = 4) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{K.KALSHI_BASE}{path}?{qs}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt == retries - 1:
                raise SystemExit(f"Could not reach Kalshi: {e}")
            time.sleep(2 ** attempt)
    return {}


def fetch_trades(ticker: str, since: datetime, cap: int = 300) -> list[dict]:
    """Recent trades for one market, newest first, stopping past the window."""
    out, cursor = [], None
    while len(out) < cap:
        d = get("/markets/trades", {"ticker": ticker, "limit": 100, "cursor": cursor})
        batch = d.get("trades", [])
        if not batch:
            break
        for t in batch:
            ts = datetime.fromisoformat(t["created_time"].replace("Z", "+00:00"))
            if ts < since:
                return out
            out.append(t)
        cursor = d.get("cursor")
        if not cursor:
            break
    return out


def fnum(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def analyze_market(ticker: str, trades: list[dict], min_size: float) -> dict:
    if not trades:
        return {}
    chron = list(reversed(trades))  # oldest -> newest
    vol = sum(fnum(t.get("count_fp")) for t in trades)
    yes_notional = no_notional = 0.0
    big = block = 0
    for t in trades:
        sz = fnum(t.get("count_fp"))
        yp = fnum(t.get("yes_price_dollars"))
        if t.get("taker_side") == "yes":
            yes_notional += sz * yp
        else:
            no_notional += sz * (1 - yp)
        if sz >= min_size:
            big += 1
        if t.get("is_block_trade"):
            block += 1
    net = yes_notional - no_notional
    move = (fnum(chron[-1].get("yes_price_dollars")) -
            fnum(chron[0].get("yes_price_dollars"))) * 100
    # composite: notional flow + premiums for big/block prints + price move
    signal = abs(net) / 100 + big * 3 + block * 8 + abs(move)
    return {"ticker": ticker, "vol": vol, "net": net, "big": big,
            "block": block, "move": move, "signal": signal,
            "last": fnum(chron[-1].get("yes_price_dollars"))}


def snapshot(rows_by_ticker, args):
    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    results = []
    for tk, label in rows_by_ticker:
        trades = fetch_trades(tk, since)
        a = analyze_market(tk, trades, args.min_size)
        if a:
            a["label"] = label
            results.append(a)
    results.sort(key=lambda a: a["signal"], reverse=True)

    print(f"\n=== SHARP ACTION — last {args.hours}h "
          f"(anonymous flow; no bettor identities exist on Kalshi) ===")
    print(f"{'SIGNAL':>6}  {'VOL':>8}  {'NETFLOW$':>10}  {'DIR':>3}  "
          f"{'BIG':>3}  {'BLK':>3}  {'MOVE':>6}  {'PX':>5}  MARKET")
    print("-" * 110)
    for a in results[:args.top]:
        direction = "YES" if a["net"] > 0 else "NO"
        print(f"{a['signal']:6.0f}  {a['vol']:8.0f}  {a['net']:+10.0f}  "
              f"{direction:>3}  {a['big']:>3}  {a['block']:>3}  "
              f"{a['move']:+5.1f}c  {a['last']*100:4.0f}c  {a['label'][:54]}")
    print()
    return results


def alerts(rows_by_ticker, args):
    """Print only NEW big/block prints since last run (for scheduling)."""
    seen = set()
    if os.path.exists(SEEN_FILE):
        try:
            seen = set(json.load(open(SEEN_FILE)))
        except Exception:
            seen = set()
    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    new_seen = set(seen)
    for tk, label in rows_by_ticker:
        for t in fetch_trades(tk, since):
            tid = t.get("trade_id")
            sz = fnum(t.get("count_fp"))
            big = sz >= args.min_size
            block = t.get("is_block_trade")
            if (big or block) and tid not in seen:
                new_seen.add(tid)
                side = t.get("taker_side", "?").upper()
                yp = fnum(t.get("yes_price_dollars")) * 100
                kind = "BLOCK" if block else "BIG"
                print(f"[{kind}] {sz:.0f} @ {yp:.0f}c taker={side}  {label[:60]}")
    json.dump(sorted(new_seen), open(SEEN_FILE, "w"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", default="Spurs,Knicks")
    ap.add_argument("--abbr", default="SAS,NYK")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-size", type=float, default=200,
                    help="contracts threshold for a 'big' trade")
    ap.add_argument("--max-markets", type=int, default=50,
                    help="limit to the N most liquid markets (saves requests)")
    ap.add_argument("--alerts", action="store_true",
                    help="print only new big/block prints since last run")
    args = ap.parse_args()

    keywords = [t.strip() for t in (args.teams + "," + args.abbr).split(",") if t.strip()]
    print(f"Loading {', '.join(keywords)} markets ...", file=sys.stderr)
    events = K.fetch_open_events(keywords)
    rows = [K.build_row(m, ev.get("title", "")) for ev in events for m in ev.get("markets", [])]
    # Focus on the most liquid markets -- that's where sharps can size up.
    liquid = sorted([r for r in rows if (r.volume or 0) > 0],
                    key=lambda r: r.volume or 0, reverse=True)[:args.max_markets]
    rows_by_ticker = [(r.ticker, f"{r.title} · {r.subtitle}".strip(" ·")) for r in liquid]

    if args.alerts:
        alerts(rows_by_ticker, args)
    else:
        snapshot(rows_by_ticker, args)


if __name__ == "__main__":
    main()
