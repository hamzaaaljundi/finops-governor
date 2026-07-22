# Portfolio Governance - Design Specification

> The design-on-paper artifact for M10. Defines how one shared GPU budget is split
> across N candidate jobs to maximize total expected-distinct-coverage per dollar -
> the natural next question once a single job is governed (M2-M9).
>
> **Status:** Accepted - **Milestone:** M10 (ADR 0010) - **Consumed by:** a new
> `allocate_portfolio` entry point alongside, not replacing, the single-job `Governor`

---

## 1. The problem this module exists to solve

Every gate decision through M9 answers one question: does this one job, against its
own budget, get approved, modified, or blocked? A portfolio is a different question:
given N jobs (potentially from different teams) competing for one shared budget, how
should that budget be split to buy the most real training-signal coverage?

This is knapsack-shaped - each job has a cost and a value (already computed by the
existing diversity model, unchanged) - but naive knapsack intuition turns out to be
actively wrong here, for a reason worth stating precisely (section 2).

## 2. The algorithm that was rejected, and why (measured, not assumed)

The obvious first candidate: rank whole jobs by cost-per-distinct evaluated at each
job's own declared (or value-trimmed) variation count, fund them fully in that order,
trim only the last one that doesn't fully fit. This was implemented and benchmarked
against a true optimum before being trusted with this project's name on it.

**Method:** 8 synthetic portfolios (4-8 jobs each, randomized capacity in
{8,16,32,64,96,200}, cost-per-variation in [0.001, 0.05], declared variation counts in
[20, 3000], budget set to 15-60% of the portfolio's full-funding cost) were run
through both the whole-job-greedy heuristic and a bisection-based marginal
water-filling baseline (the textbook-optimal solution for continuous, separable,
concave resource allocation - `expected_distinct` is concave in variation count by
construction, the coupon-collector saturation effect).

**Result:**

| trial | n_jobs | budget | whole-job greedy | water-filling (near-optimal) | gap |
|---|---|---|---|---|---|
| 0 | 6 | 28.98 | 191.846 | 231.770 | 17.2% |
| 1 | 5 | 68.42 | 291.806 | 291.806 | 0.0% |
| 2 | 5 | 65.49 | 354.749 | 362.749 | 2.2% |
| 3 | 7 | 40.02 | 310.162 | 506.215 | 38.7% |
| 4 | 4 | 82.51 | 160.000 | 200.000 | 20.0% |
| 5 | 4 | 58.26 | 263.986 | 470.078 | 43.8% |
| 6 | 8 | 48.05 | 413.304 | 623.964 | 33.8% |
| 7 | 5 | 55.86 | 142.075 | 150.075 | 5.3% |

**Mean gap: 20.1%. Worst case: 43.8%.** This is not a rounding error; it is a
structural failure mode, visible on inspection of the smallest case that reproduces
it: ranking by the ratio *at a job's own endpoint* is blind to that job's own
diminishing-returns curve. A job that looks expensive per distinct at its full
requested count can be extremely cheap per distinct in its *early* range (before its
own coupon-collector saturation); whole-job greedy can dump an entire budget into one
job that looks best at its endpoint while funding every other job at zero, missing
their far better early returns. On a hand-verifiable 3-job case (capacities 8/16/32,
budget 0.5), whole-job greedy scores 20.78 against a brute-force optimum of 25.4298 -
an 18.3% gap - by funding exactly one job (33 units) and nothing else, when the
optimal allocation spreads budget across all three (8, 5, 20 units respectively).

A 20-44% gap does not meet this project's "defensible" bar. It shipped in this
document, not in the code, because a wrong first instinct - measured and corrected
before shipping - is a stronger artifact than an unmeasured "obviously fine" heuristic
would have been (the same evidence standard docs/calibration.md holds GPU-cost
constants to).

## 3. The algorithm that ships: fractional knapsack over marginal segments

Each job's concave value curve (`expected_distinct` as a function of its own variation
count) is broken into small chunks - by default 50 per job, evenly spaced from 0 to
its declared count. Every chunk from every job is pooled into one list of `(ratio,
job, cost_delta, value_delta)` segments, sorted by value-per-dollar descending, and
filled greedily until the budget runs out. This is the ordinary fractional-knapsack
algorithm from any undergraduate algorithms course, applied to marginal segments
instead of whole jobs - the novelty here is entirely the domain application, not the
algorithm, and this document says that plainly rather than implying an invented
method.

This is mathematically equivalent to marginal-value equalization ("water-filling":
both satisfy the same optimality condition for separable concave resource allocation),
but simpler to implement, explain, and audit - no shadow-price search, just build
segments, sort, fill.

**Verification against the same baselines:**

| trial | whole-job greedy | water-filling | segments (shipped) |
|---|---|---|---|
| 0 | 191.846 | 231.770 | 231.763 |
| 1 | 291.806 | 291.806 | 291.806 |
| 2 | 354.749 | 362.749 | 362.749 |
| 3 | 310.162 | 506.215 | 506.083 |
| 4 | 160.000 | 200.000 | 200.000 |
| 5 | 263.986 | 470.078 | 470.024 |
| 6 | 413.304 | 623.964 | 623.775 |
| 7 | 142.075 | 150.075 | 150.075 |

The segment algorithm tracks water-filling closely (within ~0.2% on every trial) using
a 50-point-per-job grid. On the hand-verifiable 3-job brute-force case (capacities
8/16/32, cost-per-variation 0.01/0.02/0.015, budget 0.5), the segment algorithm scores
**25.429805053378566** against a true brute-force optimum of **25.429805053378573** -
agreement to 11 decimal places, at a 40-point grid.

## 4. What the module actually does (`src/finops_governor/portfolio.py`)

```
allocate_portfolio(plans, budget_usd, cost_model, governor=None, grid_points=50)
  -> PortfolioResult(budget_usd, total_cost_usd, total_expected_distinct, jobs=(...))
```

Per candidate plan, in order:

1. **Single-scene check (v1 scope, ADR 0010 decision 7).** Checked unconditionally,
   before the gate runs, so it can never be silently masked by a BLOCK verdict a
   multi-scene job might also happen to earn. A multi-scene plan raises `ValueError`
   rather than being handled by some inconsistent partial default.
2. **The single-job gate runs once** (`Governor.with_default_checks` by default).
   - **BLOCK** (ADR 0010 decision 2): excluded before allocation runs entirely -
     never competes for shared budget, cost/value both zero, the real gate rejection
     reason is preserved verbatim for the audit trail.
   - **MODIFY** (ADR 0010 decision 3): the job enters allocation already
     value-trimmed to its justified variation count (M6.5/ADR 0007) - the portfolio
     never has to pay budget to discover waste the single-job gate already priced for
     free.
   - **APPROVE**: the job enters allocation at its own declared count, unmodified.
3. **Marginal segments are built** for every surviving job (section 3) and pooled
   into one sorted list.
4. **Segments are filled greedily** until the shared budget is exhausted; the segment
   that only partially fits is taken fractionally (a linear last-mile approximation,
   consistent with the grid's own linear-between-points approximation).

## 5. Scope and assumptions (read this)

This is a deliberately simplified v1, same posture as the diversity model's own
section 5:

1. **Single scene per job.** A multi-scene candidate needs a vector allocation
   *within* the job before it could even enter the *portfolio's* allocation - a
   nested version of this problem this module does not attempt. Rejected with a clear
   error (ADR 0010 decision 7), not silently mishandled.
2. **No cross-job redundancy detection (ADR 0010 decision 6).** If two independent
   jobs declare overlapping randomization ranges (two "robotic arm, assembly floor"
   scenes with similar lighting/azimuth grids), this module cannot see it and will
   happily fund both at full marginal value, even though their true combined coverage
   is less than the sum of their individually-computed expected-distinct values. This
   is the realistic failure mode when multiple teams generate data independently, and
   it is the natural v2 extension - named here, not discovered by a reviewer.
3. **Grid resolution is a tunable approximation, not an exact solution.** 50 points
   per job by default; finer grids cost more `CostModel.estimate()` calls (one pair
   per grid step) and converge closer to the true continuous optimum. The 11-decimal
   agreement in section 3 was measured at 40 points on a 3-job case; real portfolios
   with more jobs or wider variation-count ranges have not been separately profiled
   for grid-resolution sensitivity - a reasonable next measurement, not yet made.
4. **Cost is assumed non-decreasing in variation count for a fixed scene** (true by
   construction of the existing cost model - more frames never cost less), but the
   segment construction does not separately verify or exploit the fixed-vs-variable
   cost split the estimator internally computes (fixed per-scene ingestion vs.
   variable per-frame render time). This works correctly (segments naturally has a
   large ratio for the first grid step where fixed cost is amortized against a big
   value jump, and small ratios thereafter), but was not the design's starting
   assumption - it was discovered, and is documented here rather than treated as an
   optimization to add later.

**What a production version would need:** cross-job redundancy detection (section 5.2
- the most valuable and hardest gap); portfolio-level fairness constraints (should one
team ever be allowed to starve entirely, even if their job's marginal ratios lose
every comparison?); a formal grid-convergence study rather than a fixed default;
integration with the M7 orchestrator's audit trail so a portfolio decision is as
auditable as a single-job one.
