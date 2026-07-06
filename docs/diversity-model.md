# Diversity / Redundancy Model - Design Specification

> The design-on-paper artifact for **M4, Task 4.1** - the project's headline innovation.
> Defines how a plan's declared randomization becomes a pre-execution estimate of wasted,
> low-training-value spend. Implementation (Task 4.2) transcribes this spec.
>
> **Status:** Accepted - **Milestone:** M4 - **Consumed by:** the Governor (as a validity axis)

---

## 1. The problem this axis exists to catch

In physical-AI synthetic-data generation, the most expensive failure is not a broken
render - it is spending GPU-hours on data that is affordable and perfectly renderable yet
**predictably redundant**. Domain randomization's entire value is *coverage*: varied poses,
lighting, materials, viewpoints. A job that pours hundreds of thousands of variations into
a tiny declared parameter space samples the same handful of configurations over and over,
teaching the model almost nothing per extra dollar.

No standard tool gates on this *before* execution. This axis does.

## 2. The proxy

The check reasons over the **declared randomization** (the M1 `randomization` block) -
never over generated data - so it is deterministic and pre-execution.

For each scene that declares randomization:

```
capacity           = product of per-parameter `levels`     # distinct configurations
variations         = scene.variation_count
redundancy_ratio   = variations / capacity                 # avg samples per configuration
redundant_fraction = max(0, 1 - capacity / variations)     # share beyond first coverage
```

And - because the CheckContext already carries the per-scene cost estimate - the redundancy
is quantified in dollars, which is the whole thesis:

```
estimated_wasted_usd = scene_subtotal_usd * redundant_fraction
```

A finding fires when `redundancy_ratio` exceeds a threshold (default **2.0** - i.e. more
than half the variations are, on average, redundant). The finding is a **WARNING**: the
scene is renderable and affordable; the gate flags the waste, it does not block or trim it
(see decision 1).

## 3. Locked decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Severity | **WARNING** | Redundant data is not invalid; flag it, let the user decide. Value-driven trimming is a documented future enhancement. |
| 2 | Capacity model | **Product of `levels`** | The combinatorial count of distinct configurations under independence - the honest first cut. |
| 3 | Threshold | **redundancy_ratio > 2.0** (tunable) | Some oversampling is legitimate (stochastic robustness); flag only clear waste. |
| 4 | No randomization declared | **No finding** | You cannot judge coverage that was never declared. The check refuses to guess. |
| 5 | Granularity | **Per scene** | `variation_count` and `randomization` are per-scene; findings are too. |

## 4. Worked examples (verified against the real cost model, A10G)

| Scene | levels | capacity | variations | ratio | redundant | scene cost | wasted | verdict |
|---|---|---|---|---|---|---|---|---|
| Well-spread | 12x5x8 | 480 | 500 | 1.04x | 4.0% | $0.24 | $0.01 | clean (below threshold) |
| Redundant | 12x8 | 96 | 5,000 | 52x | 98.1% | $2.27 | **$2.22** | WARNING |
| Production | 4x4 | 16 | 50,000 (x2 cam) | 3,125x | ~100% | $373.30 | **$373.18** | WARNING |

The production case is the point: a $373 job whose spend is almost entirely redundant,
flagged before any GPU spins up.

## 5. Scope and assumptions (read this)

This is a deliberately simplified **proxy**, not a trained value model. Its assumptions -
and therefore its limits - are stated plainly:

1. **Parameter independence.** Joint capacity is the product of per-axis levels; real
   parameters can be correlated, so true distinct-configuration count may be lower.
2. **Levels-as-capacity.** `levels` is the declared count of *meaningfully distinct* values
   per axis (a modeling choice by the plan's author). Continuous ranges are treated as
   discretized into `levels` cells; two near-identical continuous samples are assumed not
   meaningfully distinct.
3. **Ideal-spread sampling.** `redundant_fraction` assumes the first `capacity` variations
   each hit a distinct configuration. Real random sampling collides (coupon-collector
   effect), so true coverage of all configurations needs *more* than `capacity` samples -
   the proxy is therefore optimistic about coverage and conservative about flagging.
4. **Ranges ignored.** The proxy uses `levels`, not the declared `min`/`max` widths (those
   are reserved for a future domain-gap axis).
5. **Declared-input trust (circularity).** The proxy trusts the self-declared `levels`.
   Today a human authors the plan; at M6 the *LLM planner* authors it - meaning the
   component being governed also writes the inputs to its own governor. A planner that
   inflates `levels` (e.g. declaring 1,000 levels per axis) passes the gate while
   generating redundant data. The gate still catches the common real-world failure -
   honest over-generation against honestly declared ranges - but it does not defend
   against adversarial or sloppy declarations. A production version would add
   plausibility checks on declared ranges (is 1,000 lighting levels physically
   meaningful?) or derive effective levels from the executor's actual sampler rather
   than the planner's claim.

**What a production version would need:** modeling parameter correlations; estimating actual
coverage from the sampler's distribution (or its coupon-collector expectation); declaration
plausibility checks or executor-derived levels (see assumption 5); and, ultimately,
embedding-space diversity of the target data - which requires a *learned* predictor to stay
pre-execution, since measuring it directly would require rendering (and thus spending) the
very GPU-hours the gate exists to protect.

Framing redundancy as a pre-execution gate is the contribution; this proxy is a credible,
honest v1 of the estimate, with its gap to a production model documented rather than hidden.
