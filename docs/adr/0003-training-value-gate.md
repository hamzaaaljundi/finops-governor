# ADR 0003 — The gate reasons about training value, not only cost and renderability

**Status:** Accepted

## Context

The governor originally gated on two axes: budget (can we afford this job?) and
geometric validity (is the scene renderable / not broken?). Both are real, but in
physical-AI synthetic-data generation the most expensive failure is subtler: spending
GPU-hours generating data that is affordable and perfectly renderable yet **predictably
low training-value** — for example, hundreds of thousands of near-redundant variations
that pile up in already-covered regions of the randomization space and teach the model
almost nothing.

## Decision

Reframe the governor as a **pre-execution gate for training-value-per-GPU-dollar**. It
refuses to spend GPU-hours on jobs that are over-budget, geometrically invalid, **or**
predictably low-value — deciding before generation not just whether a job is affordable
and renderable, but whether it is *worth it*.

Cost and geometry become two validity axes among several. The headline new axis is
**diversity / redundancy gating**: a deterministic, pre-execution estimate of how much of
a job's variation budget lands in already-covered parameter space. To support it, the
plan schema declares each scene's domain randomization (which parameters vary and how
densely) via an optional `Randomization` block.

## Consequences

- The unification thesis becomes the project's headline: budget-invalidity,
  geometric-invalidity, and low-training-value are one class of problem — reasons not to
  spend GPU time, catchable before spend — feeding one `GateDecision`.
- The gate is built as composed, pluggable validity checks (cost, geometry, diversity)
  behind one interface, so new axes are additive.
- The diversity estimate is a deliberately simplified variance/spread proxy, not a
  trained value model. Its limits are documented; a production version would need more.
- The `Randomization` schema block is optional and backward-compatible: plans without it
  are still valid and still cost/geometry-gated.
- Determinism and pre-execution are preserved on every axis — the diversity check reasons
  over declared parameter ranges, never over generated data.
