# Roadmap - FinOps Governor for Synthetic Data Pipelines

> A pre-flight gate for **training-value-per-GPU-dollar**. An LLM plans the job; a
> deterministic, multi-axis gate decides whether it is worth running - refusing jobs that
> are over-budget, geometrically invalid, or predictably low training-value, before any
> GPU spend.

## Thesis

The LLM does fuzzy planning; a deterministic gate makes the final approve / modify / block
decision. A stochastic model is never the last word on spend or safety. Every validity
axis - budget, diversity, geometry - is a reason **not to spend GPU-hours**, catchable
before you spend, and one gate composes them.

The build order reflects this: the deterministic spine was built and tested before the
stochastic planner, and the headline innovation (diversity gating) before the
highest-tooling-risk milestone (USD).

## Scope

**In scope:** NL -> structured plan; pre-execution cost estimate; a deterministic gate
composing budget, diversity, and geometric-validity axes; execution stub; audit trail.

**Out of scope:** running large-scale generation (execution stubbed); GPU autoscaling;
downstream model training; validating rendered output images.

---

## Milestones

### Done

- **M0 - Foundation.** Repo scaffold, src layout, README, architecture doc, ADRs.
- **M1 - Plan schema** (`v0.1-schema`). The `GenerationPlan` Pydantic contract; strict
  validation; optional `Randomization` block (added in the training-value pivot).
- **M2 - Deterministic spine** (`v0.2-deterministic-gate`). `CostModel` interface +
  `GpuRenderCostModel` (affine, per-modality, hardware profiles as data); `BudgetGate`
  with approve / modify / block; `PlanModifier`; CI across Python 3.11-3.13.
- **M3 - Multi-axis validity gate** (`v0.3-validity-gate`). `ValidityCheck` interface,
  frozen `CheckContext`, `Finding` / `Severity` / `ValidityReport`; `CostCheck` (budget
  ported behind the interface); the composed `Governor`; documented composition precedence.
- **M4 - Diversity / redundancy gate** (`v0.4-diversity-gate`). The headline: a
  deterministic, pre-execution estimate of redundant, low-training-value spend, quantified
  in dollars; `DiversityCheck` on the Governor's default wiring.

### Remaining

- **M5 - OpenUSD geometric-validity gate** (`v0.5-usd-validity`). One more `ValidityCheck`:
  load the scene's USD stage and check asset existence, bounds, and collision (bounding-box
  overlap) - pre-render. USD tooling de-risked by a spike first. Lands the lazy-stage field
  deferred to `CheckContext` in ADR 0004.
- **M6 - Planning agent** (`v0.6-planner`). Natural language -> a schema-valid
  `GenerationPlan` (including randomization). A model API constrained by the M1 schema -
  likely no heavy framework.
- **M7 - Orchestration + audit trail** (`v0.7-orchestration`). Wire plan -> estimate ->
  gate -> verdict -> execute into a state machine with a re-plan loop on modify, and a
  structured audit log recording which axis drove each decision. LangGraph is the natural
  fit (state machine); plain Python is a defensible alternative.
- **M8 - Service, packaging, demo** (`v1.0`). CLI + `pip install` + FastAPI endpoint, a
  shipped sample stage, and a README demo showing the combined verdict on a real job.

---

## Release map

| Tag | Milestone | Proves |
|-----|-----------|--------|
| `v0.1-schema` | M1 | The contract everything leans on |
| `v0.2-deterministic-gate` | M2 | Budget decisions are deterministic + tested |
| `v0.3-validity-gate` | M3 | Cost + validity composed into one decision |
| `v0.4-diversity-gate` | M4 | **Headline: pre-execution training-value gating** |
| `v0.5-usd-validity` | M5 | Geometric validity as one axis, on real USD |
| `v0.6-planner` | M6 | NL -> valid plan |
| `v0.7-orchestration` | M7 | End-to-end, multi-axis audit trail |
| `v1.0` | M8 | Runnable tool + demo of the value thesis |

The commit history tells the argument: deterministic spine first, headline innovation
before the risky milestone, LLM last.
