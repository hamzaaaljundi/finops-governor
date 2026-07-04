# Cost Model — Design Specification

> The design-on-paper artifact for **M2, Task 2.1**. Defines *how a plan becomes a
> dollar figure* before any estimator code is written. Implementation (Task 2.3) should
> be transcription of this spec.
>
> **Status:** Accepted · **Milestone:** M2 · **Consumed by:** the budget gate (2.5/2.6),
> the audit trail (M5)

---

## 1. Purpose and the substrate-agnostic principle

The governor must estimate the cost of a synthetic-data job **before** any compute is
spent, regardless of what hardware a company runs on. Universality is a property of the
**governor**, not of any single formula.

This is achieved through a pluggable interface, not a one-size-fits-all equation:

```
Gate / verdict logic  ──consumes──▶  CostEstimate
                                        ▲ produced by
                         CostModel (interface)  ◀── the generic seam
                                        ▲ implements
                         GpuRenderCostModel(profile)   ← THIS DOCUMENT
                         CpuRenderCostModel(...)        ← future, same interface
                         TpuCostModel(...)              ← future, same interface
```

Each substrate is modeled by an implementation that reflects *that substrate's real cost
behavior*. A single formula stretched across GPU, CPU, and TPU would produce confidently
wrong numbers — the worst failure mode for a governor. Correct genericity comes from
**dispatching to the right model**, not from one lossy equation.

**This document specifies the first implementation, `GpuRenderCostModel`**, covering GPU
path-tracing / rasterization — the initial and most common substrate for digital-twin /
physical-AI rendering.

---

## 2. The three contracts

### 2.1 `CostModel` — the interface (the generic part)

A single method. Anything that turns a plan into an estimate is a valid `CostModel`; it
says nothing about hardware.

```
CostModel.estimate(plan: GenerationPlan) -> CostEstimate
```

Implemented in Python as a `Protocol` (structural typing — no forced inheritance).

### 2.2 `CostEstimate` — the output type

A rich result, never a bare float, because the modify logic (2.6) and the audit trail
(M5) need the breakdown.

| Field | Type | Purpose |
|---|---|---|
| `total_usd` | float | The figure the gate compares to budget |
| `total_gpu_hours` | float | Audit / transparency |
| `total_images` | int | Sanity + modify reasoning |
| `hardware_profile` | str | Which device this was costed against (audit) |
| `per_scene` | list[SceneCost] | Breakdown for transparency and modify targeting |

`SceneCost`: `scene_id`, `images`, `fixed_seconds`, `render_seconds`, `subtotal_usd`.

### 2.3 `HardwareProfile` — the data (what makes it multi-device)

Every hardware-dependent constant, lifted out of the formula into a passable object.
Adding a device is a new profile, not a code change.

| Field | Meaning |
|---|---|
| `name` | e.g. `"AWS g5.xlarge (A10G)"` |
| `price_per_hour_usd` | on-demand cloud price |
| `ref_render_seconds` | time for the reference frame **on this device** |
| `ref_pixels` | benchmark resolution (1920×1080 = 2,073,600) |
| `ref_samples` | benchmark samples (128) |
| `rasterize_factor` | cheap rasterized-render seconds per ref-frame pixel-share |
| `fixed_ingestion_seconds` | per-scene asset-load + BVH-build overhead |
| `contingency_factor` | cold-start / orchestration / logging multiplier |
| `vram_gb` | recorded for future use; **not** used in the estimate |

---

## 3. The cost formula (affine · per-modality · deterministic)

Upgraded from pure-linear to an **affine** model: a fixed per-scene setup cost plus
variable per-image render cost. In the M1 schema `render_settings` and `modalities` are
plan-level, so per-image cost is constant across scenes; only `variation_count`,
`cameras`, and the fixed per-scene overhead vary.

```
base_render_s(w, h, spp, PATH_TRACED) = ref_render_seconds
                                        × (w×h / ref_pixels)
                                        × (spp / ref_samples)

base_render_s(w, h,      RASTERIZED)  = rasterize_factor × (w×h / ref_pixels)   # spp = 1

modality_factor(modalities)           = Σ weight(m)  for m in modalities

per_image_s = base_render_s(...) × modality_factor(modalities)

for each scene:
    images   = variation_count × num_cameras
    scene_s  = fixed_ingestion_seconds + images × per_image_s

total_s   = (Σ scene_s) × contingency_factor
gpu_hours = total_s / 3600
cost_usd  = gpu_hours × price_per_hour_usd
```

All inputs are static properties of the plan or the profile — nothing runtime-dependent.
Same plan + same profile → identical cost, every time.

---

## 4. Per-modality weights (three-tier)

RGB path-traced rendering carries full global-illumination cost; geometric passes are
cheaper; segmentation / bbox / pose are near-free rasterized ID lookups. Modeled as
additive weights, not one blanket multiplier.

| Tier | Modalities | Weight | Rationale |
|---|---|---|---|
| Heavy | `RGB` | 1.00 | Full path-traced lighting — the base render |
| Medium | `DEPTH`, `SURFACE_NORMALS` | 0.15 | Geometric passes; compute but no GI |
| Trivial | `SEMANTIC_SEGMENTATION`, `INSTANCE_SEGMENTATION`, `BBOX_2D`, `BBOX_3D`, `POSE` | 0.02 | Near-free rasterized ID / matrix lookups |

Example: `RGB + DEPTH + SEMANTIC_SEGMENTATION + INSTANCE_SEGMENTATION + BBOX_2D`
= 1.00 + 0.15 + 0.02 + 0.02 + 0.02 = **1.21** (a 21% add, not a 5× multiply — honest
about the asymmetry).

---

## 5. Reference hardware profiles

Shipped as data (Task 2.2). **$/hr figures are illustrative and must be verified against
live cloud pricing when the pricing table is built** — they drift. `ref_render_seconds`
express relative performance anchored to the A10G baseline benchmark.

| Profile | `price_per_hour_usd` | `ref_render_seconds` | `vram_gb` | Character |
|---|---|---|---|---|
| NVIDIA T4 (`g4dn.xlarge`) | 0.526 | 3.00 | 16 | Cheap, slow |
| **NVIDIA A10G (`g5.xlarge`)** | **1.006** | **1.20** | **24** | **Mid baseline** |
| NVIDIA H100 (`p5`, partial) | 4.10 | 0.35 | 80 | Fast, expensive |

Shared constants across profiles (may also be per-profile later): `ref_pixels` = 2,073,600,
`ref_samples` = 128, `rasterize_factor` = 0.05, `fixed_ingestion_seconds` = 30.0,
`contingency_factor` = 1.15.

**Baseline benchmark anchor:** a 1920×1080, 128-SPP, path-traced RGB frame ≈ **1.2 s** on
the A10G. This single number is the model's primary assumption and main tunable; it is set
conservatively so the estimator errs toward over-prediction (see §7).

---

## 6. Worked examples (verified)

### 6.1 `minimal.json` on A10G
1 scene, 1 camera, 1 variation, 1280×720, 64 SPP, RGB, budget $50.

- `base_render_s` = 1.2 × (921,600 / 2,073,600) × (64/128) = **0.2667 s**
- modality factor (RGB) = 1.00 → `per_image_s` = 0.2667 s
- images = 1 → `scene_s` = 30 + 0.2667 = 30.27 s
- ×1.15 = 34.81 s = 0.0097 hr → × $1.006 = **$0.01** → **APPROVE**

### 6.2 `multi_scene.json` on A10G
station-a (300×2 = 600 imgs) + station-b (200×1 = 200 imgs), 1920×1080, 128 SPP,
factor 1.21, budget $2500.

- `per_image_s` = 1.2 × 1.0 × 1.0 × 1.21 = 1.452 s
- station-a: 30 + 600×1.452 = 901.20 s; station-b: 30 + 200×1.452 = 320.40 s
- total 1221.60 s ×1.15 = 1404.84 s = 0.3902 hr → × $1.006 = **$0.39** → **APPROVE**

### 6.3 Same plan, three devices (the generality made concrete)
The identical `multi_scene` plan, costed against each profile through the same code path:

| Profile | GPU-hours | Cost |
|---|---|---|
| T4 | 0.9468 | **$0.50** |
| **A10G** | 0.3902 | **$0.39** |
| H100 | 0.1274 | **$0.52** |

The cost-optimal device is the **mid-tier A10G**, not the cheapest-per-hour (T4) nor the
fastest (H100) — the speed/price ratio matters, and surfacing that is exactly what the
governor is for.

### 6.4 Production batch — where governance bites
1 scene, 125,000 variations × 4 cameras = 500,000 images, 3840×2160, 256 SPP,
RGB + DEPTH + 4× trivial (factor 1.23), A10G, budget $1000.

- `per_image_s` = 1.2 × 4.0 (4K) × 2.0 (256/128) × 1.23 = 11.808 s
- total ≈ 6,789,634 s ×… = 1886.0 GPU-hours → × $1.006 = **$1,897.33**
- vs budget $1000 → **BLOCK / MODIFY** (the gate's job in 2.5/2.6)

Costs reach the range that justifies a governor only at production scale — the realistic
FinOps dynamic. Fixed overhead dominates tiny jobs; variable render cost dominates large
ones.

---

## 7. Scope and exclusions (read this)

**The governor is substrate-agnostic.** It estimates and gates synthetic-data cost
regardless of the compute substrate, via the pluggable `CostModel` interface (§1).
CPU-farm and TPU substrates are future implementations of that same interface and do not
change the gate or governor.

**This document specifies `GpuRenderCostModel` only** — GPU path-tracing / rasterization
characterized by a `HardwareProfile`.

Deliberately excluded from *this implementation* (not from the governor), because they are
**unknowable pre-execution** and would make the estimate **non-deterministic**:

- **VRAM residency / the OOM cliff** — whether a scene fits in a given GPU's memory is a
  runtime outcome; modeling it would make one plan approve on one run and block on another.
- **Asset cache state** — whether assets are already resident vs. pulled from object
  storage is runtime state.
- **BVH-rebuild timing between scene swaps** — depends on execution order and cache.
- **Per-frame ray-depth variance** — a path-tracer's per-frame time varies with procedural
  asset placement, which doesn't exist until the frame is generated.

**Fail-safe principle.** Constants are chosen conservatively so the estimator errs toward
**over**-prediction. A governor must never *under*-predict a budget-buster; when it is
wrong, it should be wrong in the direction of blocking, not approving.

**Also out of scope:** non-render substrates (CPU/TPU) under *this* model, and local /
on-prem $/hr semantics (a different pricing basis, handled by a different profile or model).
