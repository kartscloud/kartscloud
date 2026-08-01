"""Turn simulated paths into P&L for the trades the thesis implies.

Probabilities are not edge. A 60% setup with a 1:3 payoff loses money. These
helpers price the actual bracket orders so the battery reports expectancy,
not just odds.
"""

from __future__ import annotations

import numpy as np


def bracket_pnl(
    paths: np.ndarray, entry: float, stop: float, target: float, side: str = "long",
    size: float = 1.0
) -> dict:
    """P&L of a stop/target bracket, resolved by whichever level is touched first.

    Entry is assumed filled at the first touch of `entry`; paths that never
    reach it are excluded from the trade statistics but reported as no-fills.
    Exit at the close if neither bracket is hit. Slippage is not modelled —
    treat the result as an upper bound.
    """
    if side not in ("long", "short"):
        raise ValueError("side must be 'long' or 'short'")

    n_steps = paths.shape[1]
    touched_entry = (
        (paths <= entry) if side == "long" else (paths >= entry)
    )
    filled = touched_entry.any(axis=1)
    entry_idx = np.where(filled, touched_entry.argmax(axis=1), n_steps)

    after = np.arange(n_steps)[None, :] >= entry_idx[:, None]

    if side == "long":
        hit_target = after & (paths >= target)
        hit_stop = after & (paths <= stop)
    else:
        hit_target = after & (paths <= target)
        hit_stop = after & (paths >= stop)

    t_idx = np.where(hit_target.any(axis=1), hit_target.argmax(axis=1), n_steps + 1)
    s_idx = np.where(hit_stop.any(axis=1), hit_stop.argmax(axis=1), n_steps + 1)

    exit_price = np.where(
        t_idx < s_idx, target, np.where(s_idx < t_idx, stop, paths[:, -1])
    )
    raw = (exit_price - entry) if side == "long" else (entry - exit_price)
    pnl = np.where(filled, raw, 0.0) * size

    traded = pnl[filled]
    wins = traded[traded > 0]
    losses = traded[traded < 0]
    return {
        "side": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "p_filled": float(filled.mean()),
        "p_target_first": float((t_idx < s_idx)[filled].mean()) if filled.any() else 0.0,
        "p_stop_first": float((s_idx < t_idx)[filled].mean()) if filled.any() else 0.0,
        "expectancy_per_share": float(traded.mean()) if traded.size else 0.0,
        "win_rate": float((traded > 0).mean()) if traded.size else 0.0,
        "avg_win": float(wins.mean()) if wins.size else 0.0,
        "avg_loss": float(losses.mean()) if losses.size else 0.0,
        "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.size else float("inf"),
        "pnl_p05": float(np.quantile(pnl, 0.05)),
        "pnl_p95": float(np.quantile(pnl, 0.95)),
    }


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Kelly fraction for a two-outcome bet. Returns 0 when there is no edge.

    Full Kelly is far too aggressive for a discretionary setup whose win rate
    is itself an estimate — treat this as a ceiling and size a fraction of it.
    """
    if avg_win <= 0 or avg_loss >= 0:
        return 0.0
    b = avg_win / abs(avg_loss)
    f = (win_rate * (b + 1.0) - 1.0) / b
    return float(max(0.0, f))


def straddle_value(paths: np.ndarray, strike: float) -> dict:
    """Expected terminal payoff of a straddle — a read on whether implied
    vol is rich or cheap versus the simulated distribution."""
    terminal = paths[:, -1]
    payoff = np.abs(terminal - strike)
    return {
        "strike": float(strike),
        "expected_payoff": float(payoff.mean()),
        "payoff_p50": float(np.median(payoff)),
        "payoff_p95": float(np.quantile(payoff, 0.95)),
        "p_payoff_gt_5": float((payoff > 5.0).mean()),
    }
