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

```
base_render_s(w, h, spp, PATH_TRACED) = ref_render_seconds * (w*h / ref_pixels) * (spp / ref_samples)
base_render_s(w, h,      RASTERIZED)  = rasterize_factor * (w*h / ref_pixels)     # spp = 1
per_image_s = base_render_s(...) * modality_factor(modalities)

for each scene:
    images  = variation_count * num_cameras
    scene_s = fixed_ingestion_seconds + images * per_image_s

total_s   = (sum of scene_s) * contingency_factor
gpu_hours = total_s / 3600
cost_usd  = gpu_hours * price_per_hour_usd
```

All inputs are static properties of the plan or profile - nothing runtime-dependent.

## 4. Per-modality weights (three-tier)

| Tier | Modalities | Weight |
|---|---|---|
| Heavy | `RGB` | 1.00 |
| Medium | `DEPTH`, `SURFACE_NORMALS` | 0.15 |
| Trivial | `SEMANTIC_SEGMENTATION`, `INSTANCE_SEGMENTATION`, `BBOX_2D`, `BBOX_3D`, `POSE` | 0.02 |

`modality_factor = sum of weights`. Example: RGB + DEPTH + SEMANTIC_SEGMENTATION +
INSTANCE_SEGMENTATION + BBOX_2D = 1.21.

## 5. Reference hardware profiles

$/hr figures verified against live cloud pricing (Task 2.2). AWS offers H100 only in
8-GPU nodes (~$7.50+/GPU normalized), so the H100 profile uses a single-GPU on-demand rate
from a specialized cloud.

| Profile | price_per_hour_usd | ref_render_seconds | vram_gb | Character |
|---|---|---|---|---|
| NVIDIA T4 (`g4dn.xlarge`) | 0.526 | 3.00 | 16 | Cheap, slow |
| **NVIDIA A10G (`g5.xlarge`)** | **1.006** | **1.20** | **24** | **Mid baseline** |
| NVIDIA H100 (single-GPU on-demand) | 3.29 | 0.35 | 80 | Fast, pricey |

Shared constants: `ref_pixels` = 2,073,600 (1920x1080), `ref_samples` = 128,
`rasterize_factor` = 0.05, `fixed_ingestion_seconds` = 30.0, `contingency_factor` = 1.15.

**Baseline anchor:** a 1920x1080, 128-SPP, path-traced RGB frame ~= 1.2 s on the A10G.

**Calibration status - read this.** The $/hr prices are verified against live cloud
pricing; the *render-time constants* (`ref_render_seconds`, `rasterize_factor`,
`fixed_ingestion_seconds`, the modality weights) are **illustrative engineering estimates,
chosen conservatively - not measured benchmarks**. They make the estimator's *behavior*
correct (deterministic, monotonic in resolution/samples/images, conservative) while its
*absolute accuracy* is uncalibrated. Calibrating these constants against a measured
Replicator/Isaac run - a one-day data-entry change, since every constant lives in
`hardware_profiles.json` - is the first step toward production use.

## 6. Worked examples (verified)

### 6.1 minimal.json on A10G
1 scene, 1 camera, 1 variation, 1280x720, 64 SPP, RGB, budget $50 -> **$0.01** -> APPROVE.

### 6.2 multi_scene.json on A10G
800 images, 1920x1080, 128 SPP, modality factor 1.21, budget $2500 -> **$0.39** -> APPROVE.

### 6.3 Same plan, three devices
The identical multi_scene plan through the same code path:

| Profile | GPU-hours | Cost |
|---|---|---|
| T4 | 0.9468 | **$0.50** |
| **A10G** | 0.3902 | **$0.39** |
| H100 | 0.1274 | **$0.42** |

The cost-optimal device is the mid-tier A10G, not the cheapest-per-hour (T4) nor the
fastest (H100) - surfacing that is exactly what the governor is for.

### 6.4 Production batch
500,000 images, 3840x2160, 256 SPP, A10G -> **$1,897.33** -> over a $1000 budget ->
BLOCK / MODIFY. Costs reach the range that justifies a governor only at production scale.

## 7. Scope and exclusions

**The governor is substrate-agnostic** via the `CostModel` interface; CPU and TPU models
are future implementations. This document specifies `GpuRenderCostModel` only.

Deliberately excluded from this implementation, because they are unknowable pre-execution
and would make the estimate non-deterministic: **VRAM residency / OOM**, **asset cache
state**, **BVH-rebuild timing**, **per-frame ray-depth variance**.

**Fail-safe principle:** constants are chosen conservatively so the estimator errs toward
over-prediction. A governor must never under-predict a budget-buster.
