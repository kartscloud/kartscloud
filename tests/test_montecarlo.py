"""Tests for the Monte Carlo battery.

Simulation code fails silently — a broken model still returns plausible
numbers. These check the properties that must hold analytically, so a
regression shows up as a failure rather than as a slightly different
probability nobody notices.
"""

import numpy as np
import pytest

from montecarlo import analytics, models, scenarios, strategies
from montecarlo.scenarios import SimConfig, SpyThesis


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.mark.parametrize("name", sorted(models.GENERATORS))
def test_paths_start_at_spot_and_are_positive(rng, name):
    p = models.simulate(
        name, rng, spot=100.0, n_paths=500, n_steps=20, dt=1 / 252 / 20, sigma=0.2
    )
    assert p.shape == (500, 21)
    assert np.allclose(p[:, 0], 100.0)
    assert (p > 0).all(), "prices must stay positive under a log-price model"


@pytest.mark.parametrize("name", sorted(models.GENERATORS))
def test_reproducible_given_a_seed(name):
    kw = dict(spot=100.0, n_paths=200, n_steps=10, dt=1 / 2520, sigma=0.2)
    a = models.simulate(name, np.random.default_rng(7), **kw)
    b = models.simulate(name, np.random.default_rng(7), **kw)
    assert np.array_equal(a, b)


def test_gbm_terminal_matches_analytic_moments(rng):
    """Terminal log-return of GBM is exactly normal — check both moments."""
    sigma, horizon, steps = 0.2, 1.0, 252
    p = models.gbm(rng, spot=100.0, n_paths=200_000, n_steps=steps,
                   dt=horizon / steps, sigma=sigma, mu=0.05)
    log_ret = np.log(p[:, -1] / 100.0)
    assert log_ret.mean() == pytest.approx((0.05 - 0.5 * sigma**2) * horizon, abs=0.004)
    assert log_ret.std() == pytest.approx(sigma * np.sqrt(horizon), rel=0.02)


def test_student_t_is_fatter_tailed_than_gbm(rng):
    kw = dict(spot=100.0, n_paths=100_000, n_steps=50, dt=1 / 12600, sigma=0.2)
    g = np.log(models.gbm(np.random.default_rng(1), **kw)[:, -1])
    t = np.log(models.student_t(np.random.default_rng(1), **kw)[:, -1])
    # Same variance target, heavier tails: compare an extreme quantile ratio.
    assert np.quantile(np.abs(t - t.mean()), 0.999) > np.quantile(np.abs(g - g.mean()), 0.999)


def test_heston_negative_correlation_produces_left_skew(rng):
    p = models.heston(rng, spot=100.0, n_paths=50_000, n_steps=252, dt=1 / 252,
                      sigma=0.2, rho=-0.8)
    r = np.log(p[:, -1] / 100.0)
    skew = ((r - r.mean()) ** 3).mean() / r.std() ** 3
    assert skew < 0, "rho<0 must produce a left-skewed return distribution"


def test_touch_prob_is_monotone_in_the_level(rng):
    p = models.gbm(rng, spot=100.0, n_paths=20_000, n_steps=50, dt=1 / 12600, sigma=0.3)
    probs = [analytics.touch_prob(p, lvl) for lvl in (101, 103, 105, 110)]
    assert all(a >= b for a, b in zip(probs, probs[1:]))
    assert analytics.touch_prob(p, 100.0) == 1.0


def test_first_touch_race_probabilities_sum_to_one(rng):
    p = models.gbm(rng, spot=100.0, n_paths=10_000, n_steps=50, dt=1 / 12600, sigma=0.3)
    r = analytics.first_touch_race(p, upper=103, lower=97)
    total = r["p_upper_first"] + r["p_lower_first"] + r["p_neither"]
    assert total == pytest.approx(1.0)
    assert all(0.0 <= r[k] <= 1.0 for k in ("p_upper_first", "p_lower_first", "p_neither"))


def test_symmetric_barriers_are_roughly_a_coin_flip(rng):
    """Driftless GBM with symmetric barriers must not favour either side."""
    p = models.gbm(rng, spot=100.0, n_paths=100_000, n_steps=200, dt=1 / 50400, sigma=0.3)
    r = analytics.first_touch_race(p, upper=102, lower=98)
    assert r["p_upper_first"] == pytest.approx(r["p_lower_first"], abs=0.02)


def test_gap_fill_counts_paths_opening_on_either_side(rng):
    paths = np.array([[750.0, 749.0, 748.0], [750.0, 751.0, 752.0], [745.0, 747.0, 749.0]])
    opens = paths[:, 0]
    # Path 0 fills downward, path 1 never does, path 2 fills upward.
    assert analytics.gap_fill_prob(paths, 748.0, opens) == pytest.approx(2 / 3)


def test_close_buckets_partition_the_distribution(rng):
    p = models.gbm(rng, spot=744.25, n_paths=20_000, n_steps=50, dt=1 / 12600, sigma=0.15)
    buckets = analytics.close_bucket_probs(p, [740, 744.25, 748, 752.5])
    assert sum(buckets.values()) == pytest.approx(1.0)


def test_max_drawdown_bounds():
    paths = np.array([[100.0, 110.0, 99.0, 105.0]])
    assert analytics.max_drawdown(paths)[0] == pytest.approx(1 - 99 / 110)


def test_prob_ci_narrows_with_more_paths():
    narrow = analytics.prob_ci(0.5, 1_000_000)
    wide = analytics.prob_ci(0.5, 100)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])
    assert 0.0 <= wide[0] and wide[1] <= 1.0


def test_bracket_pnl_resolves_target_before_stop():
    # Rises to the target without ever touching the stop.
    paths = np.tile(np.linspace(748.0, 756.0, 20), (100, 1))
    r = strategies.bracket_pnl(paths, entry=748.0, stop=743.0, target=752.5, side="long")
    assert r["p_filled"] == 1.0
    assert r["p_target_first"] == 1.0
    assert r["expectancy_per_share"] == pytest.approx(4.5)


def test_bracket_pnl_short_side_is_mirrored():
    paths = np.tile(np.linspace(752.5, 745.0, 20), (100, 1))
    r = strategies.bracket_pnl(paths, entry=752.5, stop=756.0, target=748.0, side="short")
    assert r["p_target_first"] == 1.0
    assert r["expectancy_per_share"] > 0


def test_bracket_pnl_reports_no_fill_when_entry_never_trades():
    paths = np.full((50, 10), 760.0)
    r = strategies.bracket_pnl(paths, entry=748.0, stop=743.0, target=752.5, side="long")
    assert r["p_filled"] == 0.0
    assert r["expectancy_per_share"] == 0.0


def test_bracket_pnl_rejects_bad_side():
    with pytest.raises(ValueError):
        strategies.bracket_pnl(np.ones((2, 2)), 1, 1, 1, side="sideways")


def test_kelly_is_zero_without_edge():
    assert strategies.kelly_fraction(win_rate=0.3, avg_win=1.0, avg_loss=-1.0) == 0.0
    assert strategies.kelly_fraction(win_rate=0.6, avg_win=2.0, avg_loss=-1.0) > 0.0


def test_open_mixture_puts_mass_in_the_gap_zone():
    thesis = SpyThesis(p_gap_up=0.45)
    opens = scenarios.simulate_open(np.random.default_rng(3), thesis, 50_000)
    in_zone = ((opens >= thesis.gap_low) & (opens <= thesis.gap_high)).mean()
    # At least the mixture weight — the diffusive branch can land in the zone
    # too, so the observed share is strictly above p_gap_up.
    assert 0.45 <= in_zone < 0.55
    assert opens.min() < thesis.prior_close, "the mixture must allow gap-down opens"


def test_monday_session_returns_coherent_probabilities():
    r = scenarios.monday_session(SpyThesis(), SimConfig(n_paths=5_000), model="student_t")
    lv = r["levels"]
    # Touching a farther level cannot be more likely than a nearer one.
    assert lv["breakout_752.5"] <= lv["gap_low_750"]
    assert lv["up_760"] <= lv["up_755"]
    assert 0.0 <= r["gap_fill_748"] <= 1.0
    assert sum(r["close_buckets"].values()) == pytest.approx(1.0)


def test_week_ahead_can_hold_the_pivot():
    """Regression: the spot sits exactly on the pivot, so column 0 must be
    excluded or every path is scored as an immediate break."""
    r = scenarios.week_ahead(SpyThesis(), SimConfig(n_paths=5_000))
    assert r["p_never_broke_744.25"] > 0.0


def test_earnings_move_scales_with_implied():
    cfg = SimConfig(n_paths=20_000)
    small = scenarios.earnings_event("AAA", 100.0, 0.05, cfg)
    big = scenarios.earnings_event("AAA", 100.0, 0.15, cfg)
    assert big["mean_abs_move"] > small["mean_abs_move"]
    assert small["p_move_exceeds_implied"] == pytest.approx(0.5, abs=0.03)


def test_earnings_drift_bias_tilts_direction_not_magnitude():
    cfg = SimConfig(n_paths=40_000)
    neutral = scenarios.earnings_event("BBB", 100.0, 0.10, cfg, drift_bias=0.0)
    bullish = scenarios.earnings_event("BBB", 100.0, 0.10, cfg, drift_bias=0.5)
    assert bullish["p_up_gt_10pct"] > neutral["p_up_gt_10pct"]
    assert bullish["mean_abs_move"] == pytest.approx(neutral["mean_abs_move"], rel=0.05)


def test_correlated_basket_respects_correlation():
    cfg = SimConfig(n_paths=40_000)
    spots = {"SPY": 744.25, "PLTR": 168.0, "AMD": 215.0}
    vols = {"SPY": 0.14, "PLTR": 0.6, "AMD": 0.5}
    independent = scenarios.correlated_basket(cfg, spots, vols, np.eye(3))
    correlated = scenarios.correlated_basket(
        cfg, spots, vols, np.array([[1, 0.8, 0.8], [0.8, 1, 0.8], [0.8, 0.8, 1.0]])
    )
    assert correlated["p_all_up"] > independent["p_all_up"]


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        models.simulate("crystal_ball", np.random.default_rng(0), spot=1, n_paths=1,
                        n_steps=1, dt=1, sigma=0.1)
