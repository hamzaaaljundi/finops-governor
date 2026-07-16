# Calibration Protocol - Measuring the Render Constants

> The design-on-paper artifact for **M9, Task 9.1** - written BEFORE any GPU is rented.
> Defines what gets measured, how, on what hardware, the acceptance criteria, and the
> spend cap. Task 9.2 executes this protocol verbatim; Task 9.3 lands the numbers.
>
> **Status:** Accepted - **Milestone:** M9 - **Consumed by:** hardware_profiles.json, cost-model.md section 5

---

## 1. Purpose and scope

`docs/cost-model.md` section 5 states plainly that the render-time constants are
illustrative engineering estimates. This protocol converts the **A10G baseline row** -
the reference profile every worked example anchors on - into **measured** constants:

| Constant | Today | After |
|---|---|---|
| `ref_render_seconds` (1920x1080, 128 spp, path-traced RGB) | 1.20 (estimate) | measured |
| `fixed_ingestion_seconds` (app start + stage load) | 30.0 (estimate) | measured |
| Modality weight: DEPTH / SURFACE_NORMALS tier | 0.15 (estimate) | measured |
| Modality weight: annotation tier (seg / bbox) | 0.02 (estimate) | measured |
| `rasterize_factor` | 0.05 (estimate) | measured |

**Deliberately out of scope:** T4 and H100 remain estimates (calibrating one baseline
proves the method; renting three GPUs proves nothing extra) - their rows gain a note
that they are scaled estimates relative to the measured baseline. Scene-complexity
dependence (BVH, asset count) stays excluded, as the cost model already documents.

## 2. Environment (the exact hardware the profile models)

- **Instance:** AWS `g5.xlarge` (1x NVIDIA A10G 24 GB) - the literal machine the
  `a10g` profile row prices at $1.006/hr on-demand.
- **AMI:** NVIDIA GPU-Optimized AMI (or AWS Deep Learning Base GPU AMI) - driver and
  container toolkit preinstalled.
- **Workload:** NVIDIA Isaac Sim container from NGC, **headless**, driving Omniverse
  Replicator. Record the exact container tag, driver version, and Isaac version in the
  run log - constants are meaningless without their environment pinned.
- **Prerequisite with lead time (do this FIRST):** a fresh AWS account has a G-family
  vCPU quota of 0. Request a quota increase to 4 vCPUs for "Running On-Demand G and VT
  instances" several days before the session. Also: an NGC account for the container
  pull.

## 3. The workload

A simple Replicator-driven scene analogous to the repo's `valid.usda` fixture: ground
plane, two primitive assets, one camera - deliberately minimal, because the constant
being measured is the per-frame render cost at reference settings, not scene-complexity
scaling (excluded by the model). The scene script is the Task 9.4 adapter's output,
which makes the calibration session double as the adapter's live test.

**Run matrix** (each run: render 120 frames, discard the first 20 as warm-up -
shader/JIT compilation makes early frames unrepresentative - and compute mean and
standard deviation of the steady-state 100):

| Run | Settings | Measures |
|---|---|---|
| R1 | 1920x1080, 128 spp, path-traced, RGB only | `ref_render_seconds` (the anchor) |
| R2 | 1280x720, 64 spp, path-traced, RGB only | affine scaling check: model predicts R2 = R1 x (720p px / 1080p px) x (64/128) |
| R3 | R1 settings + DEPTH + SURFACE_NORMALS | the medium-tier modality weight |
| R4 | R1 settings + semantic seg + 2D bbox | the annotation-tier modality weight |
| R5 | 1920x1080, real-time (rasterized) mode, RGB | `rasterize_factor` |
| I1 | cold start to first-frame-ready, 3 trials | `fixed_ingestion_seconds` |

Timing source: wall-clock around Replicator's per-frame write, from the run logs.
Everything captured raw: `nvidia-smi` snapshot, container tag, timestamps, the full
console log per run - committed under `docs/calibration/` so the run is auditable.

## 4. Acceptance criteria (decided now, not after seeing numbers)

1. **Stability:** steady-state coefficient of variation (std/mean) < 20% per run;
   otherwise extend the run to 300 frames before accepting.
2. **Model sanity:** the affine prediction for R2 lands within **2x** of measurement.
   The model is affine by design; reality has fixed per-frame overheads - a factor-2
   corridor is the honest tolerance. If it lands outside, the deviation is DOCUMENTED
   in cost-model.md as a known model limit, not force-fitted.
3. **Fail-safe rounding:** constants land in `hardware_profiles.json` rounded
   **conservatively upward** (the M2 principle: a governor must never under-predict a
   budget-buster).
4. Whatever the numbers are, they ship. A measured 3.1 s/frame is a better constant
   than an estimated 1.2 - the deliverable is calibration, not confirmation.

## 5. Budget cap and runbook

- **Hard cap: $40.** Expected: one session <= 6 hours of g5.xlarge (~$7) plus ~2 hours
  of contingency/setup fumbling on a second day if needed.
- Runbook order: launch -> pull container -> smoke-render 10 frames -> R1 -> I1 (x3) ->
  R2-R5 -> pull logs off the instance -> **TERMINATE** (not stop; confirm the EBS
  volume is deleted). Set a phone timer at launch; an idle GPU instance is exactly the
  waste this project gates.
- If the session dies mid-way: R1 + I1 alone are sufficient to ship 9.3 (the anchor
  constant and ingestion are the load-bearing pair); R2-R5 improve it.

## 6. What the result will and will not claim

One scene, one driver, one container version, 100-frame steady states: a **calibration
point**, not a benchmark suite. cost-model.md section 5 will say exactly that: measured
on the reference hardware under a pinned environment, run logs committed, constants
rounded conservatively - and scene-complexity variance remains excluded by design.
