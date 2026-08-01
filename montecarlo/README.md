# Monte Carlo battery

Turns a level-based trading thesis into probabilities, sensitivities, and trade
expectancy. Built around one concrete setup — SPY pivoting on 744.25 with a
750–752.5 gap zone, a 748 fill target, and PLTR/AMD earnings in the same week —
but the levels are all config, so any thesis of the same shape drops in.

```bash
pip install numpy scipy pandas
python -m montecarlo.run_all --paths 200000 --spot 744.25 --vol 0.14 --drift -0.06 --out reports
pytest tests -q
```

Writes `reports/report.md` (readable) and `reports/results.json` (everything).

## What runs

Six path models, each on every scenario, so model disagreement is visible
instead of averaged away:

| model | what it adds |
|---|---|
| `gbm` | baseline lognormal |
| `student_t` | fat tails at a variance-matched scale |
| `merton_jump` | compound-Poisson headline jumps |
| `heston` | stochastic vol, `rho<0` for realistic left skew |
| `regime_switch` | two-state calm/stress Markov vol clustering |
| `block_bootstrap` | resampled returns, no distribution assumed |

Scenarios: Monday intraday (gap-mixture open → 5-minute path with a dampened
opening chop), the week off the pivot at 30-minute granularity, single-name
earnings gaps calibrated to the implied move, and a Cholesky-correlated
SPY/PLTR/AMD basket. On top of those: a vol sweep, a drift sweep, a
convergence check, and a trade book that prices the long-the-gap-fill and
short-the-failed-break brackets with expectancy, profit factor, and Kelly.

## Reading the output

- **Level probabilities are close-to-close sampled.** A touch between sampled
  bars is missed, so every touch number is a mild *under*estimate.
- **The conditional numbers are the useful ones.** "P(752.5 breaks)" is close
  to a coin flip and tells you nothing; "given the break, P(follow-through to
  755) vs P(round trip below 744.25)" is the number the trade lives on.
- **Check the vol sweep before quoting anything.** P(touch 752.5) runs 36% →
  61% across a 10–24% vol assumption. The vol input dominates every headline
  probability, and "expecting less volatility" is a guess.
- **The trade book's negative expectancy is a result, not a bug.** Under these
  assumptions both brackets lose: the stops are inside the noise. That is the
  battery working — it is priced before the money is on it.
- The convergence table exists so nobody reads a second decimal off 1,000 paths.

## What this is not

Not a forecast, and not calibrated to market data — the vol, drift, gap
probability, and implied moves are hand-entered from a Sunday text message.
Garbage in, precisely-quantified garbage out. To make it real, replace
`SpyThesis` defaults with realised vol and the actual option-implied move, and
feed `block_bootstrap` a genuine return history via its `historical` argument.
