#!/usr/bin/env python3
"""
report.py -- visual report comparing Kalshi's implied probability ("Kalshi") to
this tool's fair value ("Here") for each value bet, with graphs + statistics.

Generates PNG charts and a short markdown README in scripts/report/.
Requires matplotlib (pip install matplotlib). Reuses kalshi_nba_bets.py.

    python3 scripts/report.py --top 20 --min-edge 0.05
"""
from __future__ import annotations

import argparse
import os
import statistics
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import kalshi_nba_bets as K

OUT = os.path.join(os.path.dirname(__file__), "report")


def short(r: K.Row, n: int = 42) -> str:
    sub = (r.subtitle or r.title).replace(" points scored", "").strip()
    return (sub[:n] + "…") if len(sub) > n else sub


def chart_top_bets(bets, path):
    """Grouped horizontal bars: Kalshi implied vs Here fair, per bet."""
    bets = bets[::-1]  # best at top
    labels = [f"{b.period}/{b.metric}: {short(b, 34)}" for b in bets]
    y = range(len(bets))
    fig, ax = plt.subplots(figsize=(11, max(4, 0.45 * len(bets))))
    h = 0.4
    ax.barh([i + h/2 for i in y], [b.implied*100 for b in bets], height=h,
            label="Kalshi (implied)", color="#c44e52")
    ax.barh([i - h/2 for i in y], [b.fair*100 for b in bets], height=h,
            label="Here (fair value)", color="#4c72b0")
    ax.set_yticks(list(y)); ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Probability (%)"); ax.set_xlim(0, 100)
    ax.set_title("Top value bets — Kalshi vs Here")
    ax.legend(loc="lower right"); ax.grid(axis="x", alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_scatter(rows, path):
    """Every priced market with a fair value: implied (x) vs fair (y)."""
    pts = [r for r in rows if r.fair is not None and r.implied is not None]
    fig, ax = plt.subplots(figsize=(7, 7))
    edges = [(r.fair - r.implied) * 100 for r in pts]
    sc = ax.scatter([r.implied*100 for r in pts], [r.fair*100 for r in pts],
                    c=edges, cmap="coolwarm", vmin=-25, vmax=25, s=22, alpha=0.8,
                    edgecolors="k", linewidths=0.2)
    ax.plot([0, 100], [0, 100], "k--", lw=1, alpha=0.6, label="fair = implied")
    ax.set_xlabel("Kalshi implied (%)"); ax.set_ylabel("Here fair value (%)")
    ax.set_title("Fair value vs Kalshi price (off-diagonal = edge)")
    fig.colorbar(sc, label="edge = fair − implied (pts)")
    ax.legend(loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_quarter_totals(rows, path):
    """Per-quarter total ladders: Kalshi points + fitted Here curve."""
    fig, ax = plt.subplots(figsize=(9, 5.5))
    colors = {"Q1": "#4c72b0", "Q2": "#55a868", "Q3": "#c44e52", "Q4": "#8172b3"}
    drawn = False
    for q in ("Q1", "Q2", "Q3", "Q4"):
        grp = [r for r in rows if r.period == q and r.metric == "total"
               and r.threshold is not None and r.implied is not None]
        grp.sort(key=lambda r: r.threshold)
        if len(grp) < 3:
            continue
        drawn = True
        c = colors[q]
        ax.scatter([r.threshold for r in grp], [r.implied*100 for r in grp],
                   color=c, s=28, label=f"{q} Kalshi")
        fitted = [r for r in grp if r.fair is not None]
        if fitted:
            ax.plot([r.threshold for r in fitted], [r.fair*100 for r in fitted],
                    color=c, lw=1.5, alpha=0.7)
    ax.set_xlabel("Quarter total points (Over X.5)")
    ax.set_ylabel("P(Over) %"); ax.set_title("Quarter total ladders — Kalshi (dots) vs fitted (lines)")
    if drawn:
        ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", default="Spurs,Knicks")
    ap.add_argument("--abbr", default="SAS,NYK")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-edge", type=float, default=0.05)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    keywords = [t.strip() for t in (args.teams + "," + args.abbr).split(",") if t.strip()]
    events = K.fetch_open_events(keywords)
    rows = [K.build_row(m, ev.get("title", "")) for ev in events for m in ev.get("markets", [])]
    K.analyze(rows, None)

    bets = sorted([r for r in rows if r.ev is not None and (r.edge or 0) >= args.min_edge],
                  key=lambda r: r.ev, reverse=True)[:args.top]
    priced = [r for r in rows if r.implied is not None]
    withfair = [r for r in rows if r.fair is not None]

    chart_top_bets(bets, os.path.join(OUT, "top_bets.png"))
    chart_scatter(rows, os.path.join(OUT, "scatter.png"))
    chart_quarter_totals(rows, os.path.join(OUT, "quarter_totals.png"))

    edges = [(r.edge or 0) * 100 for r in bets]
    lines = []
    lines.append(f"# Spurs vs Knicks — Kalshi vs Here\n")
    lines.append(f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} from live Kalshi data._\n")
    lines.append("**Kalshi** = market implied probability. **Here** = this tool's fair "
                 "value (normal-fit strike ladders + de-vigged outcomes). "
                 "**Edge** = Here − Kalshi. **EV/$1** = expected profit per $1 contract.\n")

    lines.append("## Summary\n")
    lines.append(f"| Stat | Value |\n|---|---|")
    lines.append(f"| Markets found | {len(rows)} ({len(priced)} priced) |")
    lines.append(f"| Markets with a fair value | {len(withfair)} |")
    lines.append(f"| Value bets (edge ≥ {args.min_edge*100:.0f}%) | "
                 f"{len([r for r in rows if r.ev is not None and (r.edge or 0)>=args.min_edge])} |")
    if edges:
        lines.append(f"| Top-{len(bets)} mean edge | {statistics.mean(edges):.1f} pts |")
        lines.append(f"| Top-{len(bets)} median edge | {statistics.median(edges):.1f} pts |")
        lines.append(f"| Best EV/$1 | +{max(r.ev for r in bets):.2f} |")
    lines.append("")

    lines.append("## Graphs\n")
    lines.append("![Top bets](top_bets.png)\n")
    lines.append("![Fair vs implied](scatter.png)\n")
    lines.append("![Quarter totals](quarter_totals.png)\n")

    lines.append("## Each bet: Kalshi vs Here\n")
    lines.append("| # | Period | Metric | Bet | Side | Kalshi | Here | Edge | EV/$1 |")
    lines.append("|--:|---|---|---|:--:|--:|--:|--:|--:|")
    for i, b in enumerate(bets, 1):
        lines.append(f"| {i} | {b.period} | {b.metric} | {short(b)} | {b.side} | "
                     f"{b.implied*100:.1f}% | {b.fair*100:.1f}% | "
                     f"{(b.edge or 0)*100:+.1f} | {b.ev:+.2f} |")
    lines.append("\n> Analysis only, not betting advice. A flagged edge usually means "
                 "thin/stale pricing on one strike, not free money. Re-run before acting.\n")

    with open(os.path.join(OUT, "README.md"), "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote {OUT}/README.md and 3 charts ({len(bets)} bets).")


if __name__ == "__main__":
    main()
