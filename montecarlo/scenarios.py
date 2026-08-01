"""Scenarios: the trading thesis translated into simulation inputs.

The SPY setup below is Chen's Sunday note, restated in numbers:

    744.25 is the key level for the rest of the trading week. Headline next
    week: PLTR, AMD, SPCX earnings; no major headline Monday. Expecting less
    volatility, but a gap up to 750-752.5 would not be surprising. Lower-high
    structure on SPY. If 752.5 breaks -> new ATH; hard rejection -> lower.
    Monday: chop the first few hours, then fill the gap to 748. Overall thesis
    bearish with a short-term bullish rally.

Nothing here is a forecast. It is a way of asking "if that description is
roughly right, what do the odds look like, and where is it fragile?"
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import analytics, models

MINUTES_PER_SESSION = 390
TRADING_DAYS = 252


@dataclass(frozen=True)
class SpyThesis:
    """Levels and priors from the Sunday note."""

    prior_close: float = 744.25
    key_level: float = 744.25
    gap_low: float = 750.0
    gap_high: float = 752.5
    gap_fill_target: float = 748.0
    breakout_level: float = 752.5
    downside_targets: tuple = (740.0, 735.0, 730.0)
    upside_targets: tuple = (755.0, 760.0, 765.0)

    # "expecting less volatility" -> annualised vol below the long-run ~18%.
    annual_vol: float = 0.14
    # "overall thesis remain bearish w short term bullish rally": a mild
    # negative weekly drift with an up-front bullish tilt handled separately.
    annual_drift: float = -0.06
    # Probability Monday opens inside the 750-752.5 gap-up zone.
    p_gap_up: float = 0.45

    @property
    def levels(self) -> dict:
        return {
            "key_744.25": self.key_level,
            "gap_fill_748": self.gap_fill_target,
            "gap_low_750": self.gap_low,
            "breakout_752.5": self.breakout_level,
            **{f"up_{t:g}": t for t in self.upside_targets},
            **{f"dn_{t:g}": t for t in self.downside_targets},
        }


@dataclass
class SimConfig:
    n_paths: int = 200_000
    seed: int = 20260801
    models: tuple = ("gbm", "student_t", "merton_jump", "heston", "regime_switch", "block_bootstrap")
    extra_params: dict = field(default_factory=dict)


def _dt_intraday(n_steps: int) -> float:
    """One trading session split into n_steps, expressed in years."""
    return 1.0 / TRADING_DAYS / n_steps


def simulate_open(rng, thesis: SpyThesis, n_paths: int) -> np.ndarray:
    """Monday's opening print.

    A mixture, not a single distribution: with probability `p_gap_up` the open
    lands uniformly in the stated 750-752.5 zone, otherwise it is a normal
    overnight move around the prior close. The mixture is what makes the
    downstream gap-fill number meaningful — a pure diffusion open would put
    almost no mass in the gap zone and the fill question would be vacuous.
    """
    gapped = rng.random(n_paths) < thesis.p_gap_up
    gap_opens = rng.uniform(thesis.gap_low, thesis.gap_high, size=n_paths)

    overnight_vol = thesis.annual_vol * np.sqrt(1.0 / TRADING_DAYS) * 0.55
    normal_opens = thesis.prior_close * np.exp(rng.normal(0.0, overnight_vol, size=n_paths))
    return np.where(gapped, gap_opens, normal_opens)


def monday_session(
    thesis: SpyThesis, cfg: SimConfig, model: str = "student_t", n_steps: int = 78
) -> dict:
    """Monday intraday: gap-mixture open, then a path to the close.

    `n_steps=78` is 5-minute bars. Chen's "chop the first few hours then fill
    to 748" is modelled as a dampened-vol opening stretch followed by normal
    vol, rather than baked in as a directional drift.
    """
    rng = np.random.default_rng(cfg.seed)
    opens = simulate_open(rng, thesis, cfg.n_paths)
    dt = _dt_intraday(n_steps)

    # Paths are generated off a unit spot so each path can be rescaled to its
    # own opening print.
    unit = models.simulate(
        model,
        rng,
        spot=1.0,
        n_paths=cfg.n_paths,
        n_steps=n_steps,
        dt=dt,
        sigma=thesis.annual_vol,
        mu=thesis.annual_drift,
        **cfg.extra_params.get(model, {}),
    )

    # Chop: compress the first ~2 hours of returns toward the open.
    chop_steps = min(n_steps, int(n_steps * (2.0 / 6.5)))
    log_unit = np.log(unit)
    damp = np.ones(n_steps + 1)
    damp[1 : chop_steps + 1] = 0.55
    log_unit = np.cumsum(np.diff(log_unit, axis=1, prepend=0.0) * damp, axis=1)

    paths = opens[:, None] * np.exp(log_unit)

    res = {
        "scenario": "monday_session",
        "model": model,
        "n_paths": cfg.n_paths,
        "n_steps": n_steps,
        "open": {
            "mean": float(opens.mean()),
            "p_gapped_into_zone": float(
                ((opens >= thesis.gap_low) & (opens <= thesis.gap_high)).mean()
            ),
        },
        "levels": analytics.level_map(paths, thesis.levels),
        "gap_fill_748": analytics.gap_fill_prob(paths, thesis.gap_fill_target, opens),
        "race_breakout_vs_key": analytics.first_touch_race(
            paths, thesis.breakout_level, thesis.key_level
        ),
        "terminal": analytics.terminal_stats(paths),
        "close_buckets": analytics.close_bucket_probs(
            paths, [thesis.key_level, thesis.gap_fill_target, thesis.gap_low, thesis.breakout_level]
        ),
    }
    res["gap_fill_748_ci"] = analytics.prob_ci(res["gap_fill_748"], cfg.n_paths)
    return res


def week_ahead(thesis: SpyThesis, cfg: SimConfig, model: str = "regime_switch", n_days: int = 5) -> dict:
    """Full week off the 744.25 pivot, daily steps.

    This is where the 'key level for the rest of the trading week' claim gets
    tested: how often does the week close above it, and how often does price
    hold it without ever trading through?
    """
    rng = np.random.default_rng(cfg.seed + 1)
    paths = models.simulate(
        model,
        rng,
        spot=thesis.prior_close,
        n_paths=cfg.n_paths,
        n_steps=n_days * 13,  # ~30-minute granularity so barrier touches are not missed
        dt=1.0 / TRADING_DAYS / 13,
        sigma=thesis.annual_vol,
        mu=thesis.annual_drift,
        **cfg.extra_params.get(model, {}),
    )

    # Column 0 is the spot, which sits exactly on the pivot — including it
    # would score every path as an immediate break.
    held_key = float((paths[:, 1:].min(axis=1) > thesis.key_level).mean())
    return {
        "scenario": "week_ahead",
        "model": model,
        "n_paths": cfg.n_paths,
        "levels": analytics.level_map(paths, thesis.levels),
        "p_never_broke_744.25": held_key,
        "p_close_week_above_744.25": float((paths[:, -1] > thesis.key_level).mean()),
        "p_new_ath_after_752.5_break": _conditional_breakout(paths, thesis),
        "race_breakout_vs_key": analytics.first_touch_race(
            paths, thesis.breakout_level, thesis.key_level
        ),
        "terminal": analytics.terminal_stats(paths),
    }


def _conditional_breakout(paths: np.ndarray, thesis: SpyThesis) -> dict:
    """The conditional Chen actually stated: given 752.5 breaks, what follows?

    Conditioning is the whole point. Unconditional upside odds say nothing
    about whether the breakout is worth trading; the follow-through rate
    given a break is what separates 'new ATH' from 'hard rejection'.
    """
    broke = (paths >= thesis.breakout_level).any(axis=1)
    if not broke.any():
        return {"p_break": 0.0}

    sub = paths[broke]
    first_break = (sub >= thesis.breakout_level).argmax(axis=1)
    # Mask out everything at or before the break so max/min describe only the
    # post-breakout tape (vectorised — a per-path slice loop is far too slow
    # at 200k paths).
    after = np.arange(sub.shape[1])[None, :] >= first_break[:, None]
    after_max = np.where(after, sub, -np.inf).max(axis=1)
    after_min = np.where(after, sub, np.inf).min(axis=1)

    target = thesis.upside_targets[0]
    return {
        "p_break": float(broke.mean()),
        "p_follow_through_to_%g" % target: float((after_max >= target).mean()),
        "p_hard_rejection_back_below_744.25": float((after_min <= thesis.key_level).mean()),
        "median_max_after_break": float(np.median(after_max)),
    }


def earnings_event(
    ticker: str, spot: float, implied_move: float, cfg: SimConfig,
    drift_bias: float = 0.0, n_paths: int | None = None
) -> dict:
    """Single-name earnings gap: implied-move-calibrated bimodal jump.

    Options price a straddle, not a direction, so the gap is modelled as a
    two-sided mixture whose absolute size averages the implied move, with a
    fat-ish spread around it. `drift_bias` (in [-1, 1]) tilts the up/down
    split without changing the magnitude — that is the only place a view
    enters.
    """
    n_paths = n_paths or cfg.n_paths
    rng = np.random.default_rng(abs(hash(ticker)) % (2**31) + cfg.seed)

    p_up = 0.5 + 0.5 * np.clip(drift_bias, -1.0, 1.0)
    direction = np.where(rng.random(n_paths) < p_up, 1.0, -1.0)
    # Lognormal magnitude with median at the implied move; mean sits above it,
    # matching the empirical "most moves near implied, a few far beyond".
    magnitude = implied_move * np.exp(rng.normal(0.0, 0.45, size=n_paths))
    post = spot * (1.0 + direction * magnitude)

    rets = post / spot - 1.0
    return {
        "scenario": "earnings_event",
        "ticker": ticker,
        "spot": spot,
        "implied_move": implied_move,
        "p_up": float(p_up),
        "mean_abs_move": float(np.abs(rets).mean()),
        "quantiles": {
            f"p{int(q * 100)}": float(np.quantile(post, q))
            for q in (0.05, 0.25, 0.5, 0.75, 0.95)
        },
        "p_move_exceeds_implied": float((np.abs(rets) > implied_move).mean()),
        "p_up_gt_10pct": float((rets > 0.10).mean()),
        "p_down_gt_10pct": float((rets < -0.10).mean()),
        "expected_shortfall_95": float(rets[rets <= np.quantile(rets, 0.05)].mean()),
    }


def correlated_basket(
    cfg: SimConfig, spots: dict[str, float], vols: dict[str, float],
    corr: np.ndarray, n_days: int = 5
) -> dict:
    """Joint SPY / PLTR / AMD paths under a Cholesky-correlated GBM.

    Earnings week means the single names and the index are not independent
    bets; simulating them jointly is the only way to size the combined book.
    """
    rng = np.random.default_rng(cfg.seed + 7)
    names = list(spots)
    n_steps = n_days
    dt = 1.0 / TRADING_DAYS

    chol = np.linalg.cholesky(corr)
    z = rng.standard_normal((cfg.n_paths, n_steps, len(names)))
    z = z @ chol.T

    sigma = np.array([vols[n] for n in names])
    log_inc = -0.5 * sigma**2 * dt + sigma * np.sqrt(dt) * z
    log_paths = np.cumsum(log_inc, axis=1)
    terminal = np.array([spots[n] for n in names]) * np.exp(log_paths[:, -1, :])

    all_up = (terminal > np.array([spots[n] for n in names])).all(axis=1)
    return {
        "scenario": "correlated_basket",
        "names": names,
        "p_all_up": float(all_up.mean()),
        "p_all_down": float(
            (terminal < np.array([spots[n] for n in names])).all(axis=1).mean()
        ),
        "terminal_median": {n: float(np.median(terminal[:, i])) for i, n in enumerate(names)},
        "terminal_p05": {n: float(np.quantile(terminal[:, i], 0.05)) for i, n in enumerate(names)},
        "terminal_p95": {n: float(np.quantile(terminal[:, i], 0.95)) for i, n in enumerate(names)},
    }
