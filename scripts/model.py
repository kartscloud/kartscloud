#!/usr/bin/env python3
"""
model.py -- projection model that prints the MARKET / MODEL / fair¢ / fair x /
CI width / FD devig / trust table.

Unlike the ladder-fit in kalshi_nba_bets.py (which reads fair value out of Kalshi's
own prices), this is a forward model: you give it the game's expected margin,
total, per-quarter/half splits and player projections (mean & sd), and it derives
every probability analytically.

Columns
-------
  MODEL    model win/over probability                p
  fair¢    fair price in cents                       round(p*100)
  fair x   fair decimal odds                         1/p
  CI width 50% credible-interval width of the modeled quantity  1.349*sd
           (player rows use a season-prior variance -> wider, flagged "PRIOR")
  FD devig FanDuel two-way de-vigged probability (comparison book), or "--"
  trust    confidence in the estimate: high / med / low / PRIOR  (* = flagged)

Market types (in the config JSON)
  win        {mean, sd}            P(margin > 0)             margin favors the team
  cover      {mean, sd, line}      P(margin > line)          e.g. -5.5
  total_over {mean, sd, line}      P(total  > line)
  over       {mean, sd, line}      P(stat   > line)          player props
  prob       {p}                   direct probability        e.g. series price
Each market may also set: ci (override), fd (de-vigged %, 0-1 or 0-100),
fd_odds [over,under] (American odds -> de-vigged automatically), trust (override).

Usage
-----
    pip install nothing  # stdlib only
    python3 scripts/model.py --config scripts/game.example.json
    python3 scripts/model.py --config scripts/game.example.json --no-color
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

C = {"hdr": "\033[1m", "name": "\033[32m", "dim": "\033[2m", "rst": "\033[0m",
     "high": "\033[32m", "med": "\033[33m", "low": "\033[31m", "prior": "\033[35m"}


def norm_cdf(x: float, mean: float, sd: float) -> float:
    if sd <= 0:
        return 1.0 if x >= mean else 0.0
    return 0.5 * (1.0 + math.erf((x - mean) / (sd * math.sqrt(2.0))))


def american_to_prob(odds: float) -> float:
    """Implied probability (with vig) of an American moneyline price."""
    return (-odds) / (-odds + 100) if odds < 0 else 100 / (odds + 100)


def devig_two_way(a: float, b: float) -> float:
    """De-vigged probability of the first side of a two-way American market."""
    pa, pb = american_to_prob(a), american_to_prob(b)
    return pa / (pa + pb)


def model_prob(m: dict) -> float:
    t = m["type"]
    if t == "prob":
        return float(m["p"])
    mean, sd = float(m["mean"]), float(m["sd"])
    if t == "win":
        return 1.0 - norm_cdf(0.0, mean, sd)
    if t in ("cover", "total_over", "over"):
        return 1.0 - norm_cdf(float(m["line"]), mean, sd)
    raise ValueError(f"unknown market type: {t}")


def ci_width(m: dict) -> float | None:
    if "ci" in m:
        return float(m["ci"])
    if m.get("type") == "prob":
        return None
    return 1.349 * float(m["sd"])      # central 50% interval of a normal


def fd_devig(m: dict) -> float | None:
    if "fd_odds" in m:
        return devig_two_way(*m["fd_odds"])
    if "fd" in m:
        v = float(m["fd"])
        return v / 100.0 if v > 1.5 else v
    return None


def trust_of(m: dict, fd: float | None) -> str:
    if "trust" in m:
        return m["trust"]
    if m.get("type") == "over":
        return "PRIOR"
    return "high" if fd is not None else "med"


def color_trust(t: str, use: bool) -> str:
    if not use:
        return t
    base = t.rstrip("*")
    code = {"high": C["high"], "med": C["med"], "low": C["low"],
            "PRIOR": C["prior"]}.get(base, "")
    return f"{code}{t}{C['rst']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__),
                                                     "game.example.json"))
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    use_color = not args.no_color and sys.stdout.isatty()
    cfg = json.load(open(args.config))

    if cfg.get("title"):
        head = f"{C['hdr']}{cfg['title']}{C['rst']}" if use_color else cfg["title"]
        print(f"\n{head}\n")

    name_w = max(len(m["label"]) for m in cfg["markets"]) + 1
    hdr = (f"{'MARKET':<{name_w}} {'MODEL':>6} {'fair¢':>5} {'fair x':>6} "
           f"{'CI width':>8} {'FD devig':>8}  trust")
    print((C['hdr'] + hdr + C['rst']) if use_color else hdr)

    for m in cfg["markets"]:
        p = model_prob(m)
        fd = fd_devig(m)
        ci = ci_width(m)
        cents = round(p * 100)
        odds = (1.0 / p) if p > 0 else float("inf")
        trust = trust_of(m, fd)

        name = (C['name'] + f"{m['label']:<{name_w}}" + C['rst']) if use_color \
            else f"{m['label']:<{name_w}}"
        ci_s = f"{ci:.1f}pt" if ci is not None else "--"
        fd_s = f"{fd*100:.1f}%" if fd is not None else "--"
        print(f"{name} {p*100:5.1f}% {cents:>4}¢ {odds:>5.2f}x "
              f"{ci_s:>8} {fd_s:>8}  {color_trust(trust, use_color)}")

    print()
    # Where model and FanDuel disagree most -> potential edges.
    flags = []
    for m in cfg["markets"]:
        fd = fd_devig(m)
        if fd is None:
            continue
        diff = (model_prob(m) - fd) * 100
        if abs(diff) >= 3:
            flags.append((abs(diff), m["label"], diff, fd))
    if flags:
        print("Biggest model vs FanDuel gaps (edge candidates):")
        for _, label, diff, fd in sorted(flags, reverse=True):
            side = "model higher" if diff > 0 else "model lower"
            print(f"  {label:<22} {diff:+.1f} pts ({side}, FD {fd*100:.1f}%)")
        print()


if __name__ == "__main__":
    main()
