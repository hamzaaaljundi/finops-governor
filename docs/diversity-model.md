# Diversity / Redundancy Model - Design Specification

> The design-on-paper artifact for the project's headline innovation (M4, upgraded in
> M6.5 to an expected-coverage model). Defines how a plan's declared randomization
> becomes a pre-execution estimate of wasted, low-training-value spend.
>
> **Status:** Accepted (v2, value-aware) - **Milestones:** M4, M6.5 (ADR 0007) - **Consumed by:** the Governor (as a validity axis and as the value-trim target source)

---

## 1. The problem this axis exists to catch

In physical-AI synthetic-data generation, the most expensive failure is not a broken
render - it is spending GPU-hours on data that is affordable and perfectly renderable yet
**predictably redundant**. Domain randomization's entire value is *coverage*: varied poses,
lighting, materials, viewpoints. A job that pours hundreds of thousands of variations into
a tiny declared parameter space samples the same handful of configurations over and over,
teaching the model almost nothing per extra dollar.

No standard tool gates on this *before* execution. This axis does.

## 2. The model (v2: expected coverage, not best-case spread)

The check reasons over the **declared randomization** (the M1 `randomization` block) -
never over generated data - so it is deterministic and pre-execution.

For each scene that declares randomization, with `n = variation_count` and
`capacity = product of per-parameter levels`:

```
expected_distinct  = capacity * (1 - (1 - 1/capacity)^n)     # coupon-collector expectation
redundant_fraction = 1 - expected_distinct / n               # expected wasted share of spend
```

And - because the CheckContext carries the per-scene cost estimate - the waste is
quantified in money, twice over:

```
estimated_wasted_usd          = scene_subtotal_usd * redundant_fraction
effective_cost_per_distinct   = scene_subtotal_usd / expected_distinct
```

The second number is the sharpest framing this model produces: the **effective unit
price of training signal**. A production job can cost $0.0093 per image nominally while
paying $58 per distinct configuration - the number the model can actually learn from.

A finding fires when `redundant_fraction` exceeds a threshold (default **0.5**: more than
half the scene's spend is expected redundant). The finding is **MODIFIABLE** (ADR 0007):
redundancy above threshold is recoverable by construction (redundant_fraction(1) = 0 for
every capacity), and each finding carries `justified_variation_count` - the largest count
whose expected waste is within the threshold. The Governor's value-trim pass reads that
target and proposes the plan without the waste: the production example below is flagged
at $930.27 and comes back as a 26-variation proposal at ~$0.50, same expected-coverage
bar. Value trims are applied before any budget trim - waste removal costs nothing;
budget trimming costs signal.

### Why expected coverage instead of best-case (the v1 -> v2 change)

v1 assumed ideal spread: the first `capacity` variations each hit a distinct
configuration, so waste = max(0, 1 - capacity/n). That model has a cliff: 90 variations
over 96 configurations reported **zero** waste, though uniform sampling actually collides
long before capacity (the coupon-collector effect). v2 models the expectation directly:
those 90 draws hit ~58.6 distinct configurations - **~35% expected waste** - smoothly,
with no cliff. For heavily oversampled jobs the two models converge (expected coverage
approaches capacity), so v1's headline numbers survive unchanged; the difference is
entirely in the honest region near capacity, where v1 was blind.

## 3. Locked decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Severity | **MODIFIABLE** (ADR 0007; amends M4's WARNING) | Recoverable by construction: a compliant trim target always exists, so the gate proposes the plan without the waste instead of merely flagging it. |
| 2 | Capacity model | **Product of `levels`** | The combinatorial count of distinct configurations under independence - the honest first cut. |
| 3 | Coverage model | **Coupon-collector expectation** (v2) | Models real uniform-sampling collisions; smooth, no cliff, closed-form, deterministic. |
| 4 | Threshold | **redundant_fraction > 0.5** (tunable) | Fire when more than half the spend is expected redundant; some oversampling is legitimate. |
| 5 | No randomization declared | **No finding** | You cannot judge coverage that was never declared. The check refuses to guess. |
| 6 | Granularity | **Per scene** | `variation_count` and `randomization` are per-scene; findings are too. |
| 7 | Declaration plausibility | **WARNING** when a parameter claims > 64 levels or capacity exceeds variations by 100x (both tunable) | Makes the declared-input trust visible in the verdict and audit trail; never enforced, because a declaration cannot be proven dishonest pre-execution. |

## 4. Worked examples (verified against the real cost model, A10G)

| Scene | capacity | n | E[distinct] | expected waste | scene cost | wasted | $/distinct | verdict |
|---|---|---|---|---|---|---|---|---|
| Well-spread | 480 | 500 | ~311 | 37.8% | $0.24 | - | - | clean (below 0.5) |
| Near-capacity | 96 | 90 | ~58.6 | 34.9% | $0.04 | - | - | clean; v1 reported 0% here |
| Double-oversampled | 100 | 200 | ~86.6 | 56.7% | $0.11 | $0.06 | $0.0012 | WARNING; invisible to v1 |
| Redundant | 96 | 5,000 | ~96 | 98.1% | $2.27 | **$2.22** | $0.024 | WARNING |
| Production | 16 | 50,000 (x2 cam) | 16 | ~100% | $930.27 | **$929.97** | **$58.14** | WARNING |

The production row is the point, twice: a $930 job whose spend is almost entirely
redundant, flagged before any GPU spins up - and a nominal $0.0093/image job whose
effective price is **$58.14 per distinct configuration**.

## 5. Scope and assumptions (read this)

This is a deliberately simplified **proxy**, not a trained value model. Its assumptions -
and therefore its limits - are stated plainly:

1. **Parameter independence.** Joint capacity is the product of per-axis levels; real
   parameters can be correlated, so true distinct-configuration count may be lower.
2. **Levels-as-capacity.** `levels` is the declared count of *meaningfully distinct* values
   per axis (a modeling choice by the plan's author). Continuous ranges are treated as
   discretized into `levels` cells; two near-identical continuous samples are assumed not
   meaningfully distinct.
3. **Uniform independent sampling.** The coupon-collector expectation assumes the
   executor samples configurations uniformly and independently. Stratified or Sobol/latin
   samplers cover better than the expectation (the check is then conservative); adaptive
   or biased samplers cover worse (the check is then optimistic).
4. **Ranges ignored.** The model uses `levels`, not the declared `min`/`max` widths (those
   are reserved for a future domain-gap axis).
5. **Declared-input trust (circularity).** The model trusts the self-declared `levels`.
   Today a human authors the plan; at M6 the *LLM planner* authors it - meaning the
   component being governed also writes the inputs to its own governor. A planner that
   inflates `levels` (e.g. declaring 1,000 levels per axis) passes the gate while
   generating redundant data. The gate still catches the common real-world failure -
   honest over-generation against honestly declared ranges - but it does not defend
   against adversarial or sloppy declarations. A production version would add
   plausibility checks on declared ranges (is 1,000 lighting levels physically
   meaningful?) or derive effective levels from the executor's actual sampler rather
   than the planner's claim. As of M8 pre-work, egregious declarations (a parameter
   claiming > 64 levels; capacity exceeding variations by 100x) draw a plausibility
   WARNING - trust made visible in the verdict, not only here. This narrows the
   circularity; it does not close it: a planner declaring plausible-looking inflated
   levels still passes.

**What a production version would need:** modeling parameter correlations; sampler-aware
coverage (reading the executor's actual sampling strategy instead of assuming uniform);
declaration plausibility checks or executor-derived levels (see assumption 5); and,
ultimately, embedding-space diversity of the target data - which requires a *learned*
predictor to stay pre-execution, since measuring it directly would require rendering (and
thus spending) the very GPU-hours the gate exists to protect.

Framing redundancy as a pre-execution gate is the contribution; this model is a credible,
honest v2 of the estimate, with its gap to a production model documented rather than hidden.

> Dollar figures in this document reflect the session-3 MEASURED cost constants (ADR
> 0009, docs/calibration/). They passed through three stages: a pre-calibration
> hand-authored estimate ($373.18 / $23.33 per distinct); session-2 measured but
> unknowingly unlit, ~5% higher ($391.32 / $24.46); and session-3's lit-scene
> correction (2.3773x, ADR 0009), landing at the $930.27 / $58.14 figures shown above.
> The session-2 -> session-3 jump dwarfs the pre-calibration -> session-2 one, because
> the earlier figure was measuring an unlit scene doing almost no path-tracing work,
> not a real per-frame cost.
