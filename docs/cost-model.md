# Cost Model - Design Specification

> How a plan becomes a dollar figure before any estimator code runs. The governor is
> substrate-agnostic via a pluggable `CostModel` interface; this document specifies the
> first implementation, `GpuRenderCostModel`.
>
> **Status:** Accepted - **Milestone:** M2 - **Consumed by:** the budget gate, the audit trail

## 1. Substrate-agnostic principle

Universality is a property of the governor, not of a single formula. Each substrate is
modeled by an implementation of the `CostModel` interface; stretching one formula across
GPU, CPU, and TPU would produce confidently wrong numbers. This document specifies
`GpuRenderCostModel` - GPU path-tracing / rasterization, the primary substrate for
digital-twin rendering.

## 2. The three contracts

- **`CostModel`** (interface): `estimate(plan) -> CostEstimate`. Says nothing about hardware.
- **`CostEstimate`** (output): `total_usd`, `total_gpu_hours`, `total_images`,
  `hardware_profile`, and `per_scene` breakdown (`SceneCost`). Rich, not a bare float - the
  breakdown feeds the modifier, the diversity check, and the audit trail.
- **`HardwareProfile`** (data): every hardware-dependent constant lifted out of the formula
  (`price_per_hour_usd`, `ref_render_seconds`, `ref_pixels`, `ref_samples`,
  `rasterize_factor`, `fixed_ingestion_seconds`, `contingency_factor`, `vram_gb`). Adding a
  device is a data entry, not a code change.

## 3. The cost formula (affine, per-modality, deterministic)

## 3. The cost formula (affine, per-modality, deterministic)

```
base_render_s(w, h, spp, PATH_TRACED) = ref_render_seconds * (w*h / ref_pixels) * (spp / ref_samples)
base_render_s(w, h,      RASTERIZED)  = rasterize_factor * (w*h / ref_pixels)     # spp = 1
per_image_s = base_render_s(...) * modality_factor(modalities)

for each scene:
    images  = variation_count * num_cameras
    fixed_s = fixed_ingestion_seconds
              + (annot_ingestion_extra_seconds if annotation-tier modalities present)
    scene_s = fixed_s + images * per_image_s

total_s   = (sum of scene_s) * contingency_factor
gpu_hours = total_s / 3600
cost_usd  = gpu_hours * price_per_hour_usd
```

All inputs are static properties of the plan or profile - nothing runtime-dependent.

### 4. Per-modality weights (three-tier)

Weights are MEASURED (M9 calibration): on a path-traced scene, additional
annotators are nearly free - the renderer has already computed the data;
writing it is noise. Measured +0.7% for DEPTH+SURFACE_NORMALS together, +0.0%
for seg+bbox; landed fail-safe-rounded upward, kept nonzero. POSE is unmeasured
(no BasicWriter annotator) and keeps a conservative estimate.

| Tier | Modalities | Weight |
|---|---|---|
| Heavy | `RGB` | 1.00 |
| Medium | `DEPTH`, `SURFACE_NORMALS` | 0.005 each |
| Trivial | `SEMANTIC_SEGMENTATION`, `INSTANCE_SEGMENTATION`, `BBOX_2D`, `BBOX_3D` | 0.001 each |
| Unmeasured | `POSE` | 0.02 (estimate) |

`modality_factor = sum of weights`. Example: RGB + DEPTH + SEMANTIC_SEGMENTATION +
INSTANCE_SEGMENTATION + BBOX_2D = 1.008.

Annotation-tier modalities additionally cost per-scene INGESTION time, not
per-frame render time (session 3, ADR 0009): `annot_ingestion_extra_seconds`
(+14.72 s on the measured a10g) is charged once per scene when any
annotation-tier modality is requested (section 3).

## 5. Reference hardware profiles

$/hr figures verified against live cloud pricing (Task 2.2). AWS offers H100 only in
8-GPU nodes (~$7.50+/GPU normalized), so the H100 profile uses a single-GPU on-demand rate
from a specialized cloud.

| Profile | price_per_hour_usd | ref_render_seconds | vram_gb | Character |
|---|---|---|---|---|
| NVIDIA T4 (`g4dn.xlarge`) | 0.526 | 9.03 (extrapolated) | 16 | Cheap, slow |
| **NVIDIA A10G (`g5.xlarge`)** | **1.006** | **3.5897 (measured)** | **24** | **Mid baseline** |
| NVIDIA H100 (single-GPU on-demand) | 3.29 | 1.07 (extrapolated) | 80 | Fast, pricey |

Shared constants: `ref_pixels` = 2,073,600 (1920x1080), `ref_samples` = 128,
`rasterize_factor` = 0.03, `fixed_ingestion_seconds` = 38.46,
`contingency_factor` = 1.15. The a10g profile additionally carries
`annot_ingestion_extra_seconds` = 14.72: annotation modalities were measured to
cost per-scene ingestion time, not per-frame render time (session 3, r4 vs r1).

**Baseline anchor:** a 1920x1080, 128-SPP, path-traced RGB frame = 3.5897 s on
the A10G - measured on a lit scene (session 3, 2026-07-21, CV 0.051).

**Calibration status - read this.** The a10g row is **measured**: headless Isaac
Sim 4.5.0 (digest-pinned) on a rented g5.xlarge, lit path-traced scenes, per the
pre-registered protocol in docs/calibration.md, raw artifacts committed. This
supersedes the 2026-07-20 session-2 measurement (1.51 s), which timed frames
rendered unlit due to the adapter's black-frame defect (ADR 0009). T4 and H100
remain **extrapolated** - session-2 values scaled by the measured lit-correction
ratio 2.3773, not directly measured. `rasterize_factor` retains the conservative
0.03: the session-3 measurement (0.020) failed the stability criterion (CV 0.57)
and does not ship. Scene-complexity variance remains excluded by design.
One known asymmetry: `annot_ingestion_extra_seconds` is measured on a10g and
defaults to 0.0 on the extrapolated t4/h100 rows, so cross-device comparisons
under-charge the extrapolated cards by ~half a cent per scene on annotation
jobs - visible in 6.3, documented rather than invented.

## 6. Worked examples (verified)

All figures: session-3 measured constants (ADR 0009), regenerated via
session_kit/sweep_93.py.

### 6.1 minimal.json on A10G
1 scene, 1 camera, 1 variation, 1280x720, 64 SPP, RGB, budget $50 -> **$0.013**
-> APPROVE. (Fixed-overhead-dominated: at one image, the cheap-per-hour T4 is
actually cost-optimal at $0.007 - tiny jobs invert the ranking.)

### 6.2 multi_scene.json on A10G
800 images, 1920x1080, 128 SPP, modality factor 1.008 plus the annot ingestion
term, budget $2500 -> **$0.96** -> APPROVE.

### 6.3 Same plan, three devices
Measured constants narrowed the gap and made the ranking job-shape-dependent: on
a render-dominated job (the production fixture: $906.87 on H100 vs $930.27 on
A10G) the fast card's speed edge wins by ~2.5%, while jobs with a meaningful
fixed-overhead share (this example) keep the mid-tier ahead by ~2.4%. That the
answer depends on the job is the argument for computing it per job - which is
what `--advise` does.

The identical multi_scene plan through the same code path:

| Profile | GPU-hours | Cost |
|---|---|---|
| T4 | 2.3507 | **$1.24** |
| **A10G** | 0.9587 | **$0.96** |
| H100 | 0.3002 | **$0.99** |

The cost-optimal device is the mid-tier A10G, not the cheapest-per-hour (T4) nor
the fastest (H100) - surfacing that is exactly what the governor is for.

### 6.4 Production batch
500,000 images, 3840x2160, 256 SPP, A10G -> **$4,614.37** (4,586.85 GPU-hours)
-> 4.6x over a $1000 budget -> BLOCK / MODIFY. Costs reach the range that
justifies a governor only at production scale.

## 7. Scope and exclusions

**The governor is substrate-agnostic** via the `CostModel` interface; CPU and TPU models
are future implementations. This document specifies `GpuRenderCostModel` only.

Deliberately excluded from this implementation, because they are unknowable pre-execution
and would make the estimate non-deterministic: **VRAM residency / OOM**, **asset cache
state**, **BVH-rebuild timing**, **per-frame ray-depth variance**.

**Fail-safe principle:** constants are chosen conservatively so the estimator errs toward
over-prediction. A governor must never under-predict a budget-buster.
EOF