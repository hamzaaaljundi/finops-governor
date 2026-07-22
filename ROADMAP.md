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
  effective-cost-per-distinct metric ($0.0093/image nominal vs $58.14/distinct on the
  production example); value-aware modification (ADR 0007) - diversity findings are
  MODIFIABLE, the proposal is built value-pass-then-budget-pass, and the redundant production
  job (now $930.27 under session-3 measured constants) comes back as a $0.50 same-coverage proposal; a named adversarial prompt-injection
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

- **M9 - Make it real** (`v1.1-calibrated`). The governor fronting the actual
  industry stack, not just hand-authored fixtures. **Task 9.4:** a plan-to-Replicator
  adapter (`generate_replicator_script`) - pure string assembly, testable without
  Isaac Sim, emitting a standalone headless script for a single-scene plan; unknown
  randomization parameters and unsupported modalities are skipped with an in-script
  trust-boundary warning, the same philosophy as the diversity plausibility warnings.
  **Calibration (ADR 0009):** a measured EC2 g5.xlarge / A10G session found and fixed
  a black-frame defect (the adapter's only light lived inside the frame trigger, where
  `rep.create` never executes) that had understated session-2 render cost by a
  correction ratio of 2.3773x; re-measured lit-scene constants replace it
  (`ref_render_seconds` 1.51 -> 3.5897), plus a new per-scene `annot_ingestion_extra_seconds`
  term now that annotation modalities were shown to cost ingestion time, not per-frame
  render time. t4/h100 are scaled by the same ratio and marked extrapolated;
  `rasterize_factor` and one measurement point were excluded on stated statistical
  grounds rather than accepted on a single run. **Coverage honesty (calibration.md
  section 7):** real-frame Otsu pixel-clustering measured far less realized diversity
  than the declared-capacity model predicted; diagnosed as an instrument limitation
  (lighting dominates pixel distance, not the declared randomization axes) rather than
  a model failure, and the investigation surfaced a genuine adapter bug - a full
  360-degree rotation swept through both its 0 and 360 endpoints, which name the same
  physical orientation, silently losing one declared level's worth of real diversity
  per circular axis. Fixed with a period-aware, half-open interval for circular
  parameters only; partial arcs (e.g. a declared 0-180 sweep) correctly keep both
  endpoints. 311 tests.

- **M9.5 - Pitch integrity.** The project name and framing claimed more than the code
  delivered: "training-value-per-GPU-dollar" implied a validated link between declared-
  parameter redundancy and downstream model quality that does not exist anywhere in
  this repo. Renamed to **FinOps Governor for Physical AI Synthetic Data Pipelines**;
  README's opening now states plainly what the diversity axis measures (declared-
  parameter redundancy, a real pre-execution proxy) and what it does not claim
  (validated training value - see docs/diversity-model.md section 5, which already
  said this honestly before the pitch caught up to it). ADR 0008 amended: HITL
  checkpointing is not planned for this repo - it's a genuine agent-loop use case,
  and building it here would mean adding the exact pattern this ADR's Context argued
  against; it is instead a separate, LangGraph-native project. ADR 0010 pre-registers
  M10's scope before a line of its code is written - cross-job redundancy is
  explicitly out of scope for v1, named here rather than discovered by a reviewer.
  Added a docs-vs-code drift test (`tests/test_docs_dollar_figures.py`): runs the CLI
  against the same pinned fixtures the docs quote and fails CI if a dollar figure the
  code computes today doesn't appear in the living docs that describe it - the
  automated version of the five-file manual sweep this same session needed to catch
  stale session-2 figures by hand. 313 tests.

- **M10 - Portfolio governance** (ADR 0010). One shared budget, N candidate jobs -
  allocate to maximize total expected-distinct-coverage per dollar. The obvious first
  instinct (rank whole jobs by cost-per-distinct at their own declared count, fund
  fully in that order) was measured against a brute-force/water-filling optimum before
  being trusted: mean gap **20.1%**, worst case **43.8%**, across 8 synthetic
  portfolios - a real structural failure (blind to a job's own diminishing-returns
  curve), not a rounding error. What ships instead: fractional knapsack over each
  job's marginal segments - the textbook algorithm, applied to segments instead of
  whole jobs - verified to match brute-force optimum to 11 decimal places on a small
  case. BLOCKING jobs are excluded before allocation runs; MODIFIABLE jobs enter
  already value-trimmed (M6.5/ADR 0007), never at their wasteful raw cost. v1 scope,
  named rather than discovered: single scene per job, no cross-job redundancy
  detection. New CLI mode (`--portfolio a.json b.json --portfolio-budget 500`). Full
  measurement and the rejected algorithm's numbers: docs/portfolio-model.md. 334 tests.

### Remaining

- **Real-frames demo video (post-M9).** The `demo/` GIF is still the M8 VHS terminal
  recording; a video showing the M9 adapter's emitted script actually rendering on
  Isaac Sim, calibrated against the ADR 0009 measured constants, is the natural
  follow-on and the highest-ROI next move.
- **Cross-job redundancy (post-M10, ADR 0010 decision 6).** Two independent jobs
  whose declared randomization ranges overlap are currently allocated as if
  fully independent; detecting the overlap is a correlation-detection problem this
  project has not designed yet.
- Human-in-the-loop approval checkpointing (the ADR 0008 threshold) is **not** planned
  for this repo - see ADR 0008's 2026-07-22 amendment. It is being built as a separate,
  LangGraph-native project where an agent loop is the thesis rather than a graft onto
  this one.

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
| `v1.1-calibrated` | M9 | Cost estimates hold against measured Isaac Sim data; the governed plan runs on the real stack |
| `v1.2-portfolio` | M10 | One shared budget, N jobs - allocated by measured, near-optimal marginal value, not a naive heuristic |

The commit history tells the argument: deterministic spine first, headline innovation
before the risky milestone, LLM last.
