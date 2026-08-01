"""Run the full Monte Carlo battery and emit JSON + a readable report.

    python -m montecarlo.run_all --paths 200000 --out reports/

Every scenario runs under every model, so disagreement between models is
visible rather than hidden behind one number. Where models disagree widely,
the answer is model choice, not the market.
"""

from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from . import analytics, models, scenarios, strategies
from .scenarios import SimConfig, SpyThesis


def vol_sweep(thesis: SpyThesis, cfg: SimConfig, vols=(0.10, 0.12, 0.14, 0.18, 0.24)) -> list:
    """How sensitive the headline probabilities are to the vol assumption.

    "Expecting less volatility" is the single least certain input in the note,
    so it gets swept rather than assumed.
    """
    out = []
    for v in vols:
        t = SpyThesis(**{**thesis.__dict__, "annual_vol": v})
        r = scenarios.monday_session(t, cfg, model="student_t", n_steps=78)
        out.append({
            "annual_vol": v,
            "p_touch_752.5": r["levels"]["breakout_752.5"],
            "p_touch_744.25": r["levels"]["key_744.25"],
            "p_gap_fill_748": r["gap_fill_748"],
            "close_p05": r["terminal"]["quantiles"]["p5"],
            "close_p95": r["terminal"]["quantiles"]["p95"],
        })
    return out


def drift_sweep(thesis: SpyThesis, cfg: SimConfig, drifts=(-0.25, -0.12, -0.06, 0.0, 0.12)) -> list:
    """Same, for the bearish-thesis drift term."""
    out = []
    for d in drifts:
        t = SpyThesis(**{**thesis.__dict__, "annual_drift": d})
        r = scenarios.week_ahead(t, cfg, model="regime_switch")
        out.append({
            "annual_drift": d,
            "p_close_week_above_744.25": r["p_close_week_above_744.25"],
            "p_never_broke_744.25": r["p_never_broke_744.25"],
            "week_close_median": r["terminal"]["median"],
        })
    return out


def convergence_check(thesis: SpyThesis, cfg: SimConfig, sizes=(1_000, 10_000, 50_000, 200_000)) -> list:
    """Re-run one headline probability at increasing path counts.

    If the number is still drifting at 200k paths, the estimate is not
    converged and should not be quoted to two decimals.
    """
    out = []
    for n in sizes:
        c = SimConfig(n_paths=n, seed=cfg.seed)
        r = scenarios.monday_session(thesis, c, model="student_t", n_steps=78)
        p = r["levels"]["breakout_752.5"]
        lo, hi = analytics.prob_ci(p, n)
        out.append({"n_paths": n, "p_touch_752.5": p, "ci95": [lo, hi], "ci_width": hi - lo})
    return out


def trade_book(thesis: SpyThesis, cfg: SimConfig) -> dict:
    """Price the two trades the note implies, on the same simulated tape.

    Long: the short-term bullish rally, entered on the gap-fill pullback.
    Short: the bearish thesis, entered on a failed break of 752.5.
    """
    rng = np.random.default_rng(cfg.seed + 99)
    opens = scenarios.simulate_open(rng, thesis, cfg.n_paths)
    n_steps = 78
    unit = models.simulate(
        "student_t", rng, spot=1.0, n_paths=cfg.n_paths, n_steps=n_steps,
        dt=1.0 / 252 / n_steps, sigma=thesis.annual_vol, mu=thesis.annual_drift,
    )
    paths = opens[:, None] * unit

    long_gap_fill = strategies.bracket_pnl(
        paths, entry=thesis.gap_fill_target, stop=thesis.key_level - 1.0,
        target=thesis.breakout_level, side="long",
    )
    short_failed_break = strategies.bracket_pnl(
        paths, entry=thesis.breakout_level, stop=thesis.breakout_level + 3.0,
        target=thesis.gap_fill_target, side="short",
    )
    for t in (long_gap_fill, short_failed_break):
        t["kelly_fraction"] = strategies.kelly_fraction(
            t["win_rate"], t["avg_win"], t["avg_loss"]
        )
    return {
        "long_gap_fill_748": long_gap_fill,
        "short_failed_break_752.5": short_failed_break,
        "straddle_at_748": strategies.straddle_value(paths, 748.0),
    }


def run_battery(cfg: SimConfig, thesis: SpyThesis) -> dict:
    results = {"config": {"n_paths": cfg.n_paths, "seed": cfg.seed}, "thesis": thesis.__dict__}
    t0 = time.time()

    results["monday_by_model"] = {
        m: scenarios.monday_session(thesis, cfg, model=m, n_steps=78) for m in cfg.models
    }
    results["week_by_model"] = {
        m: scenarios.week_ahead(thesis, cfg, model=m) for m in cfg.models
    }
    results["vol_sweep"] = vol_sweep(thesis, cfg)
    results["drift_sweep"] = drift_sweep(thesis, cfg)
    results["convergence"] = convergence_check(thesis, cfg)
    results["trade_book"] = trade_book(thesis, cfg)

    results["earnings"] = {
        "PLTR": scenarios.earnings_event("PLTR", 168.0, 0.12, cfg),
        "AMD": scenarios.earnings_event("AMD", 215.0, 0.09, cfg),
    }

    corr = np.array([[1.0, 0.55, 0.60], [0.55, 1.0, 0.50], [0.60, 0.50, 1.0]])
    results["basket"] = scenarios.correlated_basket(
        cfg,
        spots={"SPY": thesis.prior_close, "PLTR": 168.0, "AMD": 215.0},
        vols={"SPY": thesis.annual_vol, "PLTR": 0.60, "AMD": 0.50},
        corr=corr,
    )

    results["runtime_seconds"] = round(time.time() - t0, 2)
    results["total_simulations"] = _count_sims(results, cfg)
    return results


def _count_sims(results: dict, cfg: SimConfig) -> int:
    """Rough count of paths drawn across the whole battery."""
    n = cfg.n_paths * (len(cfg.models) * 2 + 5 + 5 + 1 + 2 + 1)
    n += sum(c["n_paths"] for c in results["convergence"])
    return int(n)


def _pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def render_report(r: dict) -> str:
    """Markdown summary — the part a human actually reads."""
    t = r["thesis"]
    lines = [
        "# SPY Monte Carlo Battery",
        "",
        f"Spot/pivot **{t['prior_close']}** · vol **{t['annual_vol']:.0%}** · "
        f"drift **{t['annual_drift']:+.0%}** · **{r['config']['n_paths']:,}** paths per scenario "
        f"· **{r['total_simulations']:,}** total paths in {r['runtime_seconds']}s",
        "",
        "> Model output, not a forecast. Every number is conditional on the "
        "assumptions in `scenarios.SpyThesis`, which came from a text message, not from data.",
        "",
        "## Monday session — probability of touching each level",
        "",
        "| model | 744.25 | 748 fill | 750 | 752.5 | 755 | 740 | close>744.25 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for m, res in r["monday_by_model"].items():
        lv = res["levels"]
        above = 1.0 - sum(
            v for k, v in res["close_buckets"].items() if k.startswith("<")
        )
        lines.append(
            f"| {m} | {_pct(lv['key_744.25'])} | {_pct(res['gap_fill_748'])} | "
            f"{_pct(lv['gap_low_750'])} | {_pct(lv['breakout_752.5'])} | "
            f"{_pct(lv['up_755'])} | {_pct(lv['dn_740'])} | {_pct(above)} |"
        )

    lines += ["", "## Week ahead off the 744.25 pivot", "",
              "| model | never breaks 744.25 | closes week above | breaks 752.5 | "
              "follow-through to 755 | hard rejection |", "|---|---|---|---|---|---|"]
    for m, res in r["week_by_model"].items():
        b = res["p_new_ath_after_752.5_break"]
        lines.append(
            f"| {m} | {_pct(res['p_never_broke_744.25'])} | "
            f"{_pct(res['p_close_week_above_744.25'])} | {_pct(b.get('p_break', 0))} | "
            f"{_pct(b.get('p_follow_through_to_755', 0))} | "
            f"{_pct(b.get('p_hard_rejection_back_below_744.25', 0))} |"
        )

    lines += ["", "## Sensitivity to the volatility assumption", "",
              "| annual vol | touch 752.5 | touch 744.25 | gap fill 748 | close p05 | close p95 |",
              "|---|---|---|---|---|---|"]
    for s in r["vol_sweep"]:
        lines.append(
            f"| {s['annual_vol']:.0%} | {_pct(s['p_touch_752.5'])} | "
            f"{_pct(s['p_touch_744.25'])} | {_pct(s['p_gap_fill_748'])} | "
            f"{s['close_p05']:.2f} | {s['close_p95']:.2f} |"
        )

    lines += ["", "## Sensitivity to the bearish drift", "",
              "| annual drift | closes week above 744.25 | never breaks | median week close |",
              "|---|---|---|---|"]
    for s in r["drift_sweep"]:
        lines.append(
            f"| {s['annual_drift']:+.0%} | {_pct(s['p_close_week_above_744.25'])} | "
            f"{_pct(s['p_never_broke_744.25'])} | {s['week_close_median']:.2f} |"
        )

    lines += ["", "## Convergence", "", "| paths | P(touch 752.5) | 95% CI width |", "|---|---|---|"]
    for c in r["convergence"]:
        lines.append(f"| {c['n_paths']:,} | {_pct(c['p_touch_752.5'])} | {100 * c['ci_width']:.2f}pp |")

    lines += ["", "## Trade book (no slippage, no commissions)", "",
              "| trade | fill rate | target first | stop first | expectancy/share | "
              "profit factor | Kelly |", "|---|---|---|---|---|---|---|"]
    for name, tr in r["trade_book"].items():
        if name == "straddle_at_748":
            continue
        lines.append(
            f"| {name} | {_pct(tr['p_filled'])} | {_pct(tr['p_target_first'])} | "
            f"{_pct(tr['p_stop_first'])} | {tr['expectancy_per_share']:+.2f} | "
            f"{tr['profit_factor']:.2f} | {tr['kelly_fraction']:.1%} |"
        )
    sv = r["trade_book"]["straddle_at_748"]
    lines.append("")
    lines.append(
        f"Simulated 748 straddle expected payoff **{sv['expected_payoff']:.2f}** "
        f"(median {sv['payoff_p50']:.2f}, p95 {sv['payoff_p95']:.2f}) — compare against "
        "the actual premium to judge whether Monday's options are rich."
    )

    lines += ["", "## Earnings gaps", "",
              "| ticker | spot | implied | P(exceeds implied) | P(+10%) | P(-10%) | p05 | p95 |",
              "|---|---|---|---|---|---|---|---|"]
    for tk, e in r["earnings"].items():
        lines.append(
            f"| {tk} | {e['spot']:.2f} | {e['implied_move']:.0%} | "
            f"{_pct(e['p_move_exceeds_implied'])} | {_pct(e['p_up_gt_10pct'])} | "
            f"{_pct(e['p_down_gt_10pct'])} | {e['quantiles']['p5']:.2f} | "
            f"{e['quantiles']['p95']:.2f} |"
        )

    b = r["basket"]
    lines += ["", "## Correlated SPY / PLTR / AMD week", "",
              f"- P(all three up on the week): **{_pct(b['p_all_up'])}**",
              f"- P(all three down): **{_pct(b['p_all_down'])}**",
              "- median close: " + ", ".join(f"{k} {v:.2f}" for k, v in b["terminal_median"].items()),
              "",
              "Correlation is the risk that the single-name earnings and the index "
              "position are the same bet wearing two hats.",
              ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the SPY Monte Carlo battery.")
    ap.add_argument("--paths", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=20260801)
    ap.add_argument("--spot", type=float, default=744.25)
    ap.add_argument("--vol", type=float, default=0.14, help="annualised volatility")
    ap.add_argument("--drift", type=float, default=-0.06, help="annualised drift")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)

    thesis = SpyThesis(prior_close=args.spot, key_level=args.spot,
                       annual_vol=args.vol, annual_drift=args.drift)
    cfg = SimConfig(n_paths=args.paths, seed=args.seed)

    results = run_battery(cfg, thesis)
    report = render_report(results)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump(results, f, indent=2)
    with open(os.path.join(args.out, "report.md"), "w") as f:
        f.write(report)

    print(report)
    print(f"\nWrote {args.out}/results.json and {args.out}/report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
