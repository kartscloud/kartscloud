"""Path-generating models for the Monte Carlo battery.

Every generator returns an array of shape (n_paths, n_steps + 1) of *price*
levels, column 0 being the spot. Everything is vectorised over paths; a
`numpy.random.Generator` is passed in so runs are reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRADING_DAYS = 252


def _to_paths(spot: float, log_increments: np.ndarray) -> np.ndarray:
    """Turn per-step log returns into a price path array with the spot prepended."""
    log_paths = np.cumsum(log_increments, axis=1)
    paths = spot * np.exp(log_paths)
    return np.concatenate([np.full((paths.shape[0], 1), spot), paths], axis=1)


@dataclass(frozen=True)
class ModelSpec:
    """Human-readable label plus the kwargs a generator needs."""

    name: str
    generator: str
    params: dict


def gbm(rng, spot, n_paths, n_steps, dt, sigma, mu=0.0, **_):
    """Plain geometric Brownian motion. The baseline everything else is judged against."""
    drift = (mu - 0.5 * sigma**2) * dt
    shocks = rng.standard_normal((n_paths, n_steps)) * sigma * np.sqrt(dt)
    return _to_paths(spot, drift + shocks)


def student_t(rng, spot, n_paths, n_steps, dt, sigma, mu=0.0, df=4.0, **_):
    """Fat-tailed GBM: normal shocks swapped for a variance-matched Student-t.

    Index returns are leptokurtic; at a one-day horizon this is usually a
    better tail model than the normal without any extra calibration burden.
    """
    scale = np.sqrt((df - 2.0) / df)
    shocks = rng.standard_t(df, size=(n_paths, n_steps)) * scale
    drift = (mu - 0.5 * sigma**2) * dt
    return _to_paths(spot, drift + shocks * sigma * np.sqrt(dt))


def merton_jump(
    rng, spot, n_paths, n_steps, dt, sigma, mu=0.0, jump_intensity=2.0,
    jump_mean=-0.004, jump_std=0.02, **_
):
    """Merton jump-diffusion: diffusive noise plus compound-Poisson headline risk.

    `jump_intensity` is jumps per year. The drift is compensated so the jump
    component does not smuggle in extra expected return.
    """
    kappa = np.exp(jump_mean + 0.5 * jump_std**2) - 1.0
    drift = (mu - jump_intensity * kappa - 0.5 * sigma**2) * dt
    diffusion = rng.standard_normal((n_paths, n_steps)) * sigma * np.sqrt(dt)

    n_jumps = rng.poisson(jump_intensity * dt, size=(n_paths, n_steps))
    # Sum of N iid normals is normal with mean N*m and variance N*s^2.
    jump_component = np.where(
        n_jumps > 0,
        n_jumps * jump_mean + np.sqrt(n_jumps) * jump_std * rng.standard_normal(n_jumps.shape),
        0.0,
    )
    return _to_paths(spot, drift + diffusion + jump_component)


def heston(
    rng, spot, n_paths, n_steps, dt, sigma, mu=0.0, kappa=6.0, theta=None,
    vol_of_vol=0.9, rho=-0.75, **_
):
    """Heston stochastic volatility, full-truncation Euler.

    The negative `rho` is what produces the realistic asymmetry: down moves
    arrive with expanding vol, up moves with contracting vol.
    """
    v0 = sigma**2
    theta = v0 if theta is None else theta
    v = np.full(n_paths, v0)
    log_increments = np.empty((n_paths, n_steps))

    for i in range(n_steps):
        z1 = rng.standard_normal(n_paths)
        z2 = rho * z1 + np.sqrt(1.0 - rho**2) * rng.standard_normal(n_paths)
        v_pos = np.maximum(v, 0.0)
        sqrt_v = np.sqrt(v_pos)
        log_increments[:, i] = (mu - 0.5 * v_pos) * dt + sqrt_v * np.sqrt(dt) * z1
        v = v + kappa * (theta - v_pos) * dt + vol_of_vol * sqrt_v * np.sqrt(dt) * z2

    return _to_paths(spot, log_increments)


def regime_switch(
    rng, spot, n_paths, n_steps, dt, sigma, mu=0.0, calm_mult=0.6, stress_mult=2.2,
    p_calm_to_stress=0.04, p_stress_to_calm=0.20, stress_drift=-0.35, start_stress_prob=0.15,
    **_
):
    """Two-state Markov regime switch (calm / stress) on volatility and drift.

    Captures the thing a single-sigma model cannot: vol clusters, and the
    stressed regime carries its own negative drift.
    """
    in_stress = rng.random(n_paths) < start_stress_prob
    log_increments = np.empty((n_paths, n_steps))

    for i in range(n_steps):
        step_sigma = np.where(in_stress, sigma * stress_mult, sigma * calm_mult)
        step_mu = np.where(in_stress, mu + stress_drift, mu)
        z = rng.standard_normal(n_paths)
        log_increments[:, i] = (step_mu - 0.5 * step_sigma**2) * dt + step_sigma * np.sqrt(dt) * z

        u = rng.random(n_paths)
        switch = np.where(in_stress, u < p_stress_to_calm, u < p_calm_to_stress)
        in_stress = np.where(switch, ~in_stress, in_stress)

    return _to_paths(spot, log_increments)


def block_bootstrap(rng, spot, n_paths, n_steps, dt, sigma, historical=None, block=5, **_):
    """Stationary block bootstrap of observed returns — no distribution assumed.

    Resampling in blocks preserves short-horizon autocorrelation and vol
    clustering that an iid bootstrap destroys. Falls back to a synthetic
    fat-tailed sample when no history is supplied, so the battery still runs
    offline.
    """
    if historical is None:
        historical = rng.standard_t(4.0, size=2000) * sigma * np.sqrt(dt) * np.sqrt(0.5)
    historical = np.asarray(historical, dtype=float)

    n_blocks = int(np.ceil(n_steps / block))
    starts = rng.integers(0, len(historical), size=(n_paths, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]) % len(historical)
    sampled = historical[idx].reshape(n_paths, n_blocks * block)[:, :n_steps]
    return _to_paths(spot, sampled)


GENERATORS = {
    "gbm": gbm,
    "student_t": student_t,
    "merton_jump": merton_jump,
    "heston": heston,
    "regime_switch": regime_switch,
    "block_bootstrap": block_bootstrap,
}


def simulate(model: str, rng, **kwargs) -> np.ndarray:
    """Dispatch to a generator by name."""
    if model not in GENERATORS:
        raise KeyError(f"unknown model {model!r}; have {sorted(GENERATORS)}")
    return GENERATORS[model](rng, **kwargs)
