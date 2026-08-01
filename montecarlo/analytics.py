"""Path statistics: barrier touches, gap fills, level maps, tail risk.

These are the numbers a discretionary trader actually acts on — "what are the
odds we tag 752.5 before 744.25" — rather than a terminal-price histogram.
"""

from __future__ import annotations

import numpy as np


def touch_prob(paths: np.ndarray, level: float, spot: float | None = None) -> float:
    """Probability the path trades through `level` at any point.

    Direction is inferred from where the level sits relative to the spot.
    Note this is a close-to-close sampling of the path, so it *understates*
    intrabar touches; use a fine enough step for the horizon.
    """
    spot = paths[0, 0] if spot is None else spot
    if level >= spot:
        return float((paths.max(axis=1) >= level).mean())
    return float((paths.min(axis=1) <= level).mean())


def first_touch_race(paths: np.ndarray, upper: float, lower: float) -> dict:
    """Which barrier gets hit first — the only framing that maps to a bracket order."""
    up_hit = paths >= upper
    dn_hit = paths <= lower
    n_steps = paths.shape[1]

    first_up = np.where(up_hit.any(axis=1), up_hit.argmax(axis=1), n_steps + 1)
    first_dn = np.where(dn_hit.any(axis=1), dn_hit.argmax(axis=1), n_steps + 1)

    upper_first = (first_up < first_dn).mean()
    lower_first = (first_dn < first_up).mean()
    return {
        "upper": float(upper),
        "lower": float(lower),
        "p_upper_first": float(upper_first),
        "p_lower_first": float(lower_first),
        "p_neither": float(1.0 - upper_first - lower_first),
    }


def gap_fill_prob(paths: np.ndarray, fill_level: float, open_price: np.ndarray) -> float:
    """Odds the session trades back to `fill_level` given where it opened.

    Paths that open on the far side of the fill are already filled and count
    as such — otherwise a gap-down open would be scored as a failed fill.
    """
    opened_above = open_price > fill_level
    filled = np.where(opened_above, paths.min(axis=1) <= fill_level, paths.max(axis=1) >= fill_level)
    return float(filled.mean())


def terminal_stats(paths: np.ndarray, quantiles=(0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)) -> dict:
    """Distribution of the closing price plus the tail measures that matter."""
    terminal = paths[:, -1]
    spot = paths[0, 0]
    rets = terminal / spot - 1.0
    q = np.quantile(terminal, quantiles)

    var95 = float(np.quantile(rets, 0.05))
    tail = rets[rets <= var95]
    return {
        "spot": float(spot),
        "mean": float(terminal.mean()),
        "median": float(np.median(terminal)),
        "std": float(terminal.std(ddof=1)),
        "quantiles": {f"p{int(p * 100)}": float(v) for p, v in zip(quantiles, q)},
        "prob_up": float((terminal > spot).mean()),
        "var_95": var95,
        "expected_shortfall_95": float(tail.mean()) if tail.size else var95,
        "max_drawdown_median": float(np.median(max_drawdown(paths))),
    }


def max_drawdown(paths: np.ndarray) -> np.ndarray:
    """Per-path peak-to-trough decline, as a positive fraction."""
    running_max = np.maximum.accumulate(paths, axis=1)
    return (1.0 - paths / running_max).max(axis=1)


def level_map(paths: np.ndarray, levels: dict[str, float]) -> dict:
    """Touch probability for every named level in the thesis."""
    return {name: touch_prob(paths, lvl) for name, lvl in levels.items()}


def close_bucket_probs(paths: np.ndarray, edges: list[float]) -> dict:
    """Probability the close lands in each bucket defined by `edges`.

    Buckets are half-open [lo, hi), with open-ended tails on both ends.
    """
    terminal = paths[:, -1]
    bounds = [-np.inf, *sorted(edges), np.inf]
    out = {}
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        label = (
            f"<{hi:g}" if lo == -np.inf else f">={lo:g}" if hi == np.inf else f"{lo:g}-{hi:g}"
        )
        out[label] = float(((terminal >= lo) & (terminal < hi)).mean())
    return out


def mc_standard_error(values: np.ndarray) -> float:
    """Standard error of a Monte Carlo mean — how much of the answer is noise."""
    values = np.asarray(values, dtype=float)
    return float(values.std(ddof=1) / np.sqrt(values.size))


def prob_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wald interval on a simulated probability. Reported so nobody reads
    a 2-decimal probability off 10k paths as if it were exact."""
    se = np.sqrt(max(p * (1.0 - p), 0.0) / n)
    return (max(0.0, p - z * se), min(1.0, p + z * se))
