#!/usr/bin/env python3
"""Render the model.py table to a dark, terminal-style PNG (screenshot look)."""
from __future__ import annotations

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import model as M

BG = "#1c1c1c"
GREY = "#9aa0a6"
WHITE = "#e8eaed"
ORANGE = "#d98c3f"   # game-level lines
GREEN = "#6ab04c"    # quarters / halves / series
YELLOW = "#e1c340"   # player props
TRUST_COL = {"high": "#6ab04c", "med": "#e1c340", "low": "#e06c5e", "PRIOR": "#b39ddb"}


def row_color(m: dict) -> str:
    if m["type"] == "over":
        return YELLOW
    lbl = m["label"]
    if any(t in lbl for t in ("Q1", "Q2", "Q3", "Q4", "Half", "SERIES")):
        return GREEN
    return ORANGE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__),
                                                     "game.example.json"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                  "report", "model_table.png"))
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    name_w = max(len(m["label"]) for m in cfg["markets"]) + 1
    hdr = (f"{'MARKET':<{name_w}}{'MODEL':>7}{'fair¢':>7}{'fair x':>8}"
           f"{'CI width':>10}{'FD devig':>10}   trust")

    lines = []  # (text, color, is_trust_split)
    for m in cfg["markets"]:
        p = M.model_prob(m)
        fd = M.fd_devig(m)
        ci = M.ci_width(m)
        trust = M.trust_of(m, fd)
        ci_s = f"{ci:.1f}pt" if ci is not None else "--"
        fd_s = f"{fd*100:.1f}%" if fd is not None else "--"
        body = (f"{m['label']:<{name_w}}{p*100:6.1f}%{round(p*100):>6}¢"
                f"{1/p:>7.2f}x{ci_s:>10}{fd_s:>10}   ")
        lines.append((body, row_color(m), trust))

    n = len(lines) + 3
    fig_h = 0.34 * n + 0.4
    fig, ax = plt.subplots(figsize=(9.6, fig_h))
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG); ax.axis("off")
    mono = {"family": "monospace", "fontsize": 12}

    y = 1.0
    dy = 1.0 / n
    ax.text(0.5, y, "Code", color=WHITE, ha="center", fontweight="bold",
            transform=ax.transAxes, **{"family": "monospace", "fontsize": 13})
    y -= dy
    ax.text(0.02, y, cfg.get("title", ""), color=GREY, transform=ax.transAxes,
            **{"family": "monospace", "fontsize": 9})
    y -= dy
    ax.text(0.02, y, hdr, color=GREY, fontweight="bold", transform=ax.transAxes, **mono)
    y -= dy
    for body, col, trust in lines:
        ax.text(0.02, y, body + trust, color=col, transform=ax.transAxes, **mono)
        # overlay the trust word in its own color: leading spaces align in monospace
        ax.text(0.02, y, " " * len(body) + trust,
                color=TRUST_COL.get(trust.rstrip("*"), GREY),
                transform=ax.transAxes, **mono)
        y -= dy

    fig.tight_layout(pad=0.6)
    fig.savefig(args.out, dpi=150, facecolor=BG)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
