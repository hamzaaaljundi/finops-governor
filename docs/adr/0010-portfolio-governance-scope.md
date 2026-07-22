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
constraint. Fractional knapsack has a well-known greedy-by-ratio heuristic; the
novelty here is entirely the domain application - governed GPU-spend allocation across
competing teams - not the algorithm, and this ADR names that plainly rather than
implying an invented method.

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
4. **Allocation strategy: greedy by expected-distinct-per-dollar**, a fractional-
   knapsack-style heuristic - well-understood, deterministic (this project's
   thesis-consistent constraint), and simple enough to audit line by line, same as
   every other decision this gate makes.
5. **The greedy heuristic's optimality gap is measured, not asserted.** Before this
   ships as "defensible," it is benchmarked against a brute-force or LP-relaxation
   baseline on a handful of synthetic portfolios, and the measured gap is reported in
   the design doc - the same evidence standard this project holds its calibration
   work to (docs/calibration.md's own "measured, not force-fitted" principle applies
   here too).
6. **Cross-job redundancy is explicitly out of scope for v1**, named here rather than
   discovered by a reviewer. Detecting it correctly requires comparing declared
   parameter spaces across jobs that may use entirely different scene definitions,
   parameter names, and units - a correlation-detection problem materially harder than
   anything this gate currently does, and one where a wrong answer (false-positive
   "these overlap" or false-negative "these don't") is worse than the current honest
   silence. It is named as the natural v2 extension, not silently deferred.

## Consequences

- M10 ships a portfolio allocator whose per-job math is identical to, and reuses
  wholesale, the existing single-job diversity/cost models - no parallel coverage
  model to maintain.
- The project can honestly say what it does ("allocates a shared budget across
  independent jobs by expected coverage per dollar, with a measured heuristic gap")
  and what it does not ("does not detect redundant coverage across different teams'
  jobs") in the same sentence, before anyone asks.
- A future v2 that models cross-job redundancy has a clean entry point: this ADR is
  where that gap was named, not a retrofit.
- If the measured greedy gap (decision 5) turns out to be large on adversarial
  portfolios, that finding ships too - "the heuristic has a documented weakness at
  extreme value skew" is a stronger result than silence, consistent with this
  project's calibration protocol's clause 4: whatever the numbers are, they ship.
