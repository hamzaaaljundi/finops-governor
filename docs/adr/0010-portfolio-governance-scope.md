# ADR 0010 - Portfolio governance scope: per-job allocation, cross-job redundancy out of scope for v1

**Status:** Accepted (pre-registered before M10 implementation, per this project's
design-first convention - see ADR 0007's "before a line of code")

## Context

Every gate decision so far governs one job against one budget. The natural next
question - and the one identified as this project's highest-novelty remaining move -
is a queue: N candidate jobs (potentially from different teams) sharing one fixed
budget, where the governor's job is to allocate that budget to maximize total expected
distinct-coverage per dollar spent, not merely to approve or reject each job in
isolation.

This is knapsack-shaped: each job has a cost and an expected-distinct-configurations
value (already computed by the existing diversity model, unchanged); the allocator
picks a subset (or partial allocation) maximizing total value under one budget
constraint. The obvious first-instinct heuristic - greedy by cost-per-distinct
evaluated at each job's own declared variation count - was tried and measured before
being trusted; see Decision 4 for why it was rejected in favor of a different,
still-simple, still-deterministic algorithm.

The harder, more interesting version of this problem is **cross-job redundancy**: if
Team A's job and Team B's job both declare overlapping randomization ranges (e.g. two
"robotic arm, assembly floor" scenes with similar lighting/azimuth grids), the true
combined distinct-coverage across both jobs is less than the sum of each job's
individually-computed expected-distinct. A per-job allocator cannot see this; it can
allocate optimally within each job and still pay twice for materially the same
coverage. This is the realistic failure mode when multiple teams generate data
independently, and it is the version of this problem a systems-minded reviewer will
ask about.

## Decision

1. **v1 allocates over independent, per-job expected-distinct values.** Each candidate
   job's `expected_distinct` and `redundant_fraction` are computed exactly as the
   existing single-job diversity model already computes them (ADR/M6.5 math,
   unchanged) - no new coverage model, no cross-job comparison.
2. **BLOCKING findings exclude a job from the portfolio before allocation runs.** A
   geometrically invalid or unrecoverably over-budget job never competes for shared
   budget; it is filtered out, same precedence rule as the single-job gate (ADR 0007
   decision 5).
3. **MODIFIABLE jobs enter allocation at their value-trimmed cost, not their raw
   declared cost.** The existing value-trim pass (ADR 0007) runs first, per job; the
   portfolio allocator then sees each job's already-waste-corrected cost and expected
   distinct count. Waste removal still costs nothing and happens before any
   budget-level decision, consistent with the existing single-job ordering.
4. **Allocation strategy: marginal water-filling, not whole-job greedy - measured,
   not assumed.** The obvious first candidate - rank jobs by cost-per-distinct
   evaluated at each job's own declared variation count, fund them in that order, trim
   only the last one to fit - was implemented and benchmarked against a true optimum
   (brute-force on small cases; verified to agree within ~1%) across 8 synthetic
   portfolios (4-8 jobs each, randomized capacity/cost/declared-n, budget 15-60% of
   full-portfolio cost). **Measured mean gap: 20.1% from optimal, worst case 43.8%.**
   The failure mode is visible on inspection: ranking by the ratio *at a job's
   endpoint* is blind to that job's own diminishing-returns curve (`expected_distinct`
   is concave in variation count - coupon-collector saturation), so greedy can dump an
   entire budget into one job that looks cheapest at its full declared count while
   funding other jobs at zero, missing their excellent *early* marginal returns. A
   20-44% gap does not meet this project's "defensible" bar.

   The algorithm that ships instead: **fractional knapsack over per-job marginal
   segments**, not whole jobs. Each job's concave `expected_distinct` curve is broken
   into small chunks (e.g. n=0-50, 50-100, ...) with a cost and value delta each;
   every chunk from every job is pooled into one list, sorted by value-per-dollar
   descending, and filled greedily until the budget runs out - ordinary fractional
   knapsack, just applied to marginal segments instead of whole jobs. This is
   mathematically equivalent to marginal-value equalization (both satisfy the same
   optimality condition for separable concave allocation; sorting all segments by
   ratio and bisecting on a shadow price find the same solution), but simpler to
   implement, explain, and audit: no shadow-price search, just build segments, sort,
   fill. Verified against the brute-force baseline: **25.42980505... vs. true optimum
   25.42980505...**, matching to the 11th decimal on the tiny case, and within ~0.02%
   of a separate 60-iteration bisection cross-check on all 8 synthetic portfolios (see
   docs/portfolio-model.md for the full table).
5. **Every algorithm choice in this ADR is backed by a measured number, not an
   assumption - including the one that got rejected.** The whole-job-greedy gap above
   is reported precisely because a wrong first instinct, measured and corrected before
   shipping, is more defensible than an unmeasured "obviously fine" heuristic would
   have been. This is the same evidence standard docs/calibration.md holds GPU-cost
   constants to, applied to an algorithm instead of a hardware measurement.
6. **Cross-job redundancy is explicitly out of scope for v1**, named here rather than
   discovered by a reviewer. Detecting it correctly requires comparing declared
   parameter spaces across jobs that may use entirely different scene definitions,
   parameter names, and units - a correlation-detection problem materially harder than
   anything this gate currently does, and one where a wrong answer (false-positive
   "these overlap" or false-negative "these don't") is worse than the current honest
   silence. It is named as the natural v2 extension, not silently deferred.
7. **Each candidate job must declare exactly one scene for v1.** The per-job
   marginal-segment curve (decision 4) needs a single scalar "how much of this job did
   we fund" - a multi-scene job would need a vector allocation *within* the job before
   it could even enter the *portfolio's* allocation, a nested version of this same
   problem this ADR has not designed. A multi-scene candidate is rejected with a clear
   error rather than silently handled by some inconsistent default (e.g. only trimming
   the first scene). Named here, surfaced while designing the implementation rather
   than after shipping it - the same "found while building, written down before it
   ships" discipline as decision 4's rejected-algorithm measurement.

## Consequences

- M10 ships a portfolio allocator whose per-job math is identical to, and reuses
  wholesale, the existing single-job diversity/cost models - no parallel coverage
  model to maintain.
- The project can honestly say what it does ("allocates a shared budget across
  independent jobs by marginal expected coverage per dollar, via fractional knapsack
  over per-job segments, matching brute-force optimum to 11 decimal places on a
  verified small case") and what it does not ("does not detect redundant coverage
  across different teams' jobs") in the same sentence, before anyone asks.
- A future v2 that models cross-job redundancy has a clean entry point: this ADR is
  where that gap was named, not a retrofit.
- The rejected whole-job-greedy measurement ships in the docs alongside the accepted
  algorithm - "here's the naive approach, here's its measured 20-44% gap, here's why
  the shipped algorithm doesn't have that problem" is a stronger artifact than only
  showing the final answer, consistent with this project's calibration protocol's
  clause 4: whatever the numbers are, they ship.
