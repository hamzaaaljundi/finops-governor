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
- **M5 - OpenUSD geometric-validity gate** (`v0.5-usd-validity`). `UsdGeometryCheck`:
  asset existence, asset-vs-environment penetration (BLOCKING), asset-vs-asset overlap
  (WARNING), camera-framing orientation proxy (WARNING) - over real, lazily loaded USD
  stages with a resting tolerance. `Governor.with_all_checks` composes all three axes;
  CLI `--geometry` flag; a minimal CLI entry point (pulled forward from M8).
- **M6 - Planning agent** (`v0.6-planner`). NL -> schema-valid `GenerationPlan`: a
  `PlannerModel` seam (live Anthropic client + scripted fake), the live
  `model_json_schema()` as the prompt's single source of truth, a bounded repair loop
  feeding verbatim validation errors back (3 attempts, then a clean `PlannerError`),
  budget authority enforced by code after validation, and the declared-input circularity
  mitigated at prompt level and documented. CLI plan mode: English in, verdict out.

- **M6.5 - Close the loop** (`v0.6.5-value-gate`). The gate acts on the waste it
  prices: the diversity model upgraded to expected coverage (coupon-collector - smooth,
  no best-case cliff, headline dollars preserved to the cent) with an
  effective-cost-per-distinct metric ($0.004/image nominal vs $23.33/distinct on the
  production example); value-aware modification (ADR 0007) - diversity findings are
  MODIFIABLE, the proposal is built value-pass-then-budget-pass, and the $373 redundant
  job comes back as a $0.20 same-coverage proposal; a named adversarial prompt-injection
  suite attacking the trust boundary; mypy (strict settings) added to CI.

- **M7 - Orchestration + audit trail** (`v0.7-orchestration`). The pipeline as pure
  node functions over one typed, immutable state (plain Python; ADR 0008 evaluates
  LangGraph and defers it with a named threshold - HITL checkpointing, parallel slow
  nodes - and a structural one-day port path). Modify strategy: adopt the gate's own
  proposal (deterministic; convergence in exactly one extra gate pass verified for all
  three modify shapes), bounded loudly at max_gate_passes. Terminal states EXECUTED /
  BLOCKED / FAILED - blocked is a governance success, not a failure. The audit trail is
  the deliverable: one frozen, serializable event per node with per-decision
  driving-axis attribution and adoption savings - the dollars-saved receipt. CLI plan
  mode runs the full pipeline (--audit saves the trail).

- **M8 - Service, packaging, demo** (`v1.0`). Declaration-plausibility warnings
  (the declared-input trust made visible in the verdict); the hardware profile advisor
  (the mid-tier-wins punchline as a feature: library, CLI `--advise`, API); the FastAPI
  service - five endpoints, the M1/M7 contracts as the API contracts verbatim, HTTP
  codes describe the transaction and never the verdict; v1.0 packaging with a
  `finops-governor` console entry point, published to TestPyPI; a reproducible VHS
  demo (the GIF is generated from `demo/demo.tape`, never hand-recorded).

### Remaining

- **M9 (post-v1.0) - Make it real.** Calibrate the render constants against a measured
  Isaac Sim run on the reference GPU (rented g5.xlarge A10G, ~one day); a thin
  plan-to-Replicator adapter and a real-frames demo video - the governor fronting the
  actual industry stack. Candidate extensions beyond M9, in docs and ADRs: a
  human-in-the-loop approval checkpoint (the ADR 0008 threshold, LangGraph's home
  ground) and portfolio governance (allocating one budget across N candidate jobs by
  expected coverage per dollar). FastAPI endpoint, `pip install` polish, a
  shipped sample stage, and a README demo (GIF) showing the combined verdict on a real
  job. The CLI itself shipped early, at M5, and gained plan mode at M6.

---

## Release map

| Tag | Milestone | Proves |
|-----|-----------|--------|
| `v0.1-schema` | M1 | The contract everything leans on |
| `v0.2-deterministic-gate` | M2 | Budget decisions are deterministic + tested |
| `v0.3-validity-gate` | M3 | Cost + validity composed into one decision |
| `v0.4-diversity-gate` | M4 | **Headline: pre-execution training-value gating** |
| `v0.5-usd-validity` | M5 | Geometric validity as one axis, on real USD |
| `v0.6-planner` | M6 | NL -> valid plan, judged by the same gate |
| `v0.6.5-value-gate` | M6.5 | **The gate removes the waste it prices** |
| `v0.7-orchestration` | M7 | End-to-end, multi-axis audit trail |
| `v1.0` | M8 | **Runnable, installable, served, demonstrated** |

The commit history tells the argument: deterministic spine first, headline innovation
before the risky milestone, LLM last.
