# Architecture

## Thesis and trust boundary

Everything upstream of the gate is **advisory**, including the LLM planner. The gate is the
only component with authority over spend, and it is fully **deterministic**: the same plan
+ same profiles + same checks produce the same decision, every time. This is what makes the
governor auditable and testable.

The gate does not ask only "can we afford this?" It asks "is this job worth the GPU spend?"
- composing three kinds of reason-not-to-spend into one verdict:

- **budget** - the estimated cost exceeds the ceiling;
- **diversity** - the job is predictably redundant (low training-value per dollar);
- **geometry** - the scene is invalid (e.g. an asset clips the floor). *(M5)*

## Pipeline

```
NL request
  -> [M6] Planning Agent (LLM)        fuzzy, advisory: NL -> GenerationPlan
  -> [M2] Cost Estimator              deterministic: plan -> CostEstimate
  -> [M3] Governor (multi-axis gate)  runs every ValidityCheck, composes findings
        - CostCheck       (M2/M3)     budget
        - DiversityCheck  (M4)        redundancy / training-value, in dollars
        - UsdGeometryCheck (M5)       asset existence, bounds, collision
  -> verdict: approve / modify / block
  -> [M7] Execution stub (approve only) + audit log
```

## Key design seams

The whole system is built on two interfaces and a strict contract, so new capability is
additive rather than invasive:

- **`CostModel` (interface).** `estimate(plan) -> CostEstimate`. The gate and the modifier
  depend on this, never on a concrete model - so a GPU, CPU, or TPU cost model is a swap,
  not a rewrite. `GpuRenderCostModel` is the one implementation today.
- **`ValidityCheck` (interface).** `check(context) -> list[Finding]`. Every axis (cost,
  diversity, geometry) is an implementation. The `Governor` depends only on the interface,
  so adding an axis is "write one check" - no gate, composition, or decision changes.
- **`GenerationPlan` (contract).** The strict Pydantic schema at the boundary between the
  fuzzy LLM output and the deterministic pipeline. Malformed plans fail loudly.

## Composition

The `Governor` runs every registered check over a frozen `CheckContext` (the plan plus its
pre-computed cost estimate), aggregates the `Finding`s into a `ValidityReport`, and resolves
one verdict by severity precedence (ADR 0005):

1. any **BLOCKING** finding -> BLOCK
2. else any **MODIFIABLE** finding -> MODIFY (cost axis only; trims variations to fit)
3. otherwise -> APPROVE (warnings, e.g. diversity, are recorded but not decisive)

The decision is order-independent and every finding is recorded for audit.

## Determinism and pre-execution

Every axis reasons over the plan and scene description - never over generated data.
Diversity reads the declared randomization; geometry reads the USD stage; neither renders
anything. This preserves the "decide before GPU spend" guarantee and keeps the verdict
reproducible. Runtime-dependent factors (VRAM residency, cache state, per-frame variance)
are deliberately excluded - they are unknowable pre-execution and would break determinism
(see `docs/cost-model.md`).
