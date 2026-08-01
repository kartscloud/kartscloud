# SPY Monte Carlo Battery

Spot/pivot **744.25** · vol **14%** · drift **-6%** · **200,000** paths per scenario · **5,461,000** total paths in 82.3s

> Model output, not a forecast. Every number is conditional on the assumptions in `scenarios.SpyThesis`, which came from a text message, not from data.

## Monday session — probability of touching each level

| model | 744.25 | 748 fill | 750 | 752.5 | 755 | 740 | close>744.25 |
|---|---|---|---|---|---|---|---|
| gbm |  54.2% |  50.4% |  89.9% |  46.3% |  26.8% |  28.8% |  66.4% |
| student_t |  53.1% |  49.0% |  89.3% |  45.2% |  25.8% |  28.1% |  66.7% |
| merton_jump |  54.2% |  50.4% |  89.9% |  46.4% |  26.9% |  28.9% |  66.4% |
| heston |  54.2% |  49.1% |  89.2% |  45.7% |  25.8% |  29.6% |  67.3% |
| regime_switch |  53.6% |  48.4% |  89.3% |  44.8% |  25.4% |  29.1% |  65.7% |
| block_bootstrap |  52.4% |  48.3% |  89.2% |  45.0% |  25.3% |  27.4% |  67.0% |

## Week ahead off the 744.25 pivot

| model | never breaks 744.25 | closes week above | breaks 752.5 | follow-through to 755 | hard rejection |
|---|---|---|---|---|---|
| gbm |   6.4% |  47.1% |  50.5% |  79.4% |  36.3% |
| student_t |   6.4% |  47.2% |  48.7% |  79.0% |  32.6% |
| merton_jump |   6.4% |  47.2% |  50.8% |  79.7% |  36.4% |
| heston |   8.0% |  54.0% |  48.8% |  73.1% |  26.7% |
| regime_switch |   5.7% |  45.1% |  45.7% |  78.4% |  34.2% |
| block_bootstrap |   5.8% |  45.3% |  46.8% |  78.3% |  34.3% |

## Sensitivity to the volatility assumption

| annual vol | touch 752.5 | touch 744.25 | gap fill 748 | close p05 | close p95 |
|---|---|---|---|---|---|
| 10% |  35.6% |  47.8% |  37.8% | 737.62 | 756.45 |
| 12% |  40.6% |  50.5% |  44.2% | 736.28 | 757.67 |
| 14% |  45.2% |  53.1% |  49.0% | 734.93 | 758.94 |
| 18% |  52.8% |  57.8% |  55.3% | 732.18 | 761.68 |
| 24% |  61.0% |  63.2% |  60.8% | 727.98 | 765.98 |

## Sensitivity to the bearish drift

| annual drift | closes week above 744.25 | never breaks | median week close |
|---|---|---|---|
| -25% |  37.3% |   4.3% | 739.72 |
| -12% |  42.6% |   5.2% | 741.63 |
| -6% |  45.1% |   5.7% | 742.51 |
| +0% |  47.6% |   6.2% | 743.40 |
| +12% |  52.6% |   7.3% | 745.17 |

## Convergence

| paths | P(touch 752.5) | 95% CI width |
|---|---|---|
| 1,000 |  47.3% | 6.19pp |
| 10,000 |  45.2% | 1.95pp |
| 50,000 |  45.2% | 0.87pp |
| 200,000 |  45.2% | 0.44pp |

## Trade book (no slippage, no commissions)

| trade | fill rate | target first | stop first | expectancy/share | profit factor | Kelly |
|---|---|---|---|---|---|---|
| long_gap_fill_748 |  78.7% |  16.9% |  63.7% | -2.31 | 0.28 | 0.0% |
| short_failed_break_752.5 |  47.8% |  26.6% |  54.3% | -0.34 | 0.80 | 0.0% |

Simulated 748 straddle expected payoff **6.35** (median 5.38, p95 15.57) — compare against the actual premium to judge whether Monday's options are rich.

## Earnings gaps

| ticker | spot | implied | P(exceeds implied) | P(+10%) | P(-10%) | p05 | p95 |
|---|---|---|---|---|---|---|---|
| PLTR | 168.00 | 12% |  50.0% |  33.0% |  32.7% | 132.34 | 203.80 |
| AMD | 215.00 | 9% |  50.1% |  20.5% |  20.3% | 180.57 | 249.37 |

## Correlated SPY / PLTR / AMD week

- P(all three up on the week): ** 25.5%**
- P(all three down): ** 27.6%**
- median close: SPY 744.11, PLTR 167.38, AMD 214.50

Correlation is the risk that the single-name earnings and the index position are the same bet wearing two hats.
