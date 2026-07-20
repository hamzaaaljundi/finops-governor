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

## 5. Reference hardware profiles - MEASURED (M9 calibration)

Shipped as data (Task 2.2). As of M9, the **A10G baseline row is measured**, not
estimated: a headless Isaac Sim 4.5.0 session on the literal reference hardware (AWS
`g5.xlarge`, driver 550.90.07, CUDA 12.4), per the pre-registered protocol in
[calibration.md](./calibration.md), with raw timing artifacts committed under
[docs/calibration/](./calibration/). T4 and H100 remain **scaled estimates relative to
the measured anchor** (same x1.258 re-anchoring ratio applied); $/hr figures must still
be verified against live cloud pricing - they drift.

| Profile | `price_per_hour_usd` | `ref_render_seconds` | `vram_gb` | Status |
|---|---|---|---|---|
| NVIDIA T4 (`g4dn.xlarge`) | 0.526 | 3.80 | 16 | scaled estimate |
| **NVIDIA A10G (`g5.xlarge`)** | **1.006** | **1.51** | **24** | **MEASURED** |
| NVIDIA H100 (single-GPU on-demand) | 3.29 | 0.45 | 80 | scaled estimate |

Shared constants: `ref_pixels` = 2,073,600, `ref_samples` = 128,
`rasterize_factor` = **0.03 (measured 0.025)**, `fixed_ingestion_seconds` = **32.0
(measured warm ~31 s)**, `contingency_factor` = 1.15.

**The measured anchor:** a 1920x1080, 128-SPP, path-traced RGB frame = **1.5061 s
mean** on the A10G (99 steady-state frames, CV 0.8%; landed as 1.51, fail-safe
rounded, with the 1.15 contingency factor carrying uncertainty headroom). The original
1.20 estimate was ~20% optimistic - which is why the protocol's rule was "whatever the
numbers are, they ship."

**Measured findings that changed the model:**

1. **Additional modalities are nearly free on a path-traced scene.** DEPTH +
   SURFACE_NORMALS together added +0.7% (weights were estimated at +15% each);
   segmentation + bboxes added +0.0% (estimated +2% each). The renderer already
   computes this data; writing it costs noise. Weights landed at 0.005 / 0.001
   (fail-safe, kept nonzero); POSE is unmeasured (no BasicWriter annotator) and keeps
   its 0.02 estimate. Governance consequence: the gate should never discourage extra
   annotations on cost grounds.
2. **The affine scaling model under-predicts cheap configurations.** At 1280x720 /
   64 SPP the affine prediction was 0.335 s/frame; measured 0.582 s - a 1.74x
   deviation (inside the pre-committed 2x corridor, documented rather than
   force-fitted). Real per-frame fixed overheads (scene sync, writer I/O) do not
   scale with pixels x samples. The model is exact at reference settings, where the
   headline examples live; a per-frame overhead term is the named structural fix if
   low-resolution estimates ever become load-bearing.
3. **Ingestion is bimodal: ~31 s warm, ~15 min cold.** First-ever container start pays
   RTX shader compilation (~900 s, cacheable and cached in any real deployment); the
   constant models the warm case, with the cold case documented here.

Environment pinned in [calibration/](./calibration/): AMI `Deep Learning Base OSS
Nvidia Driver GPU AMI (Ubuntu 22.04) 20240915`, driver 550.90.07, CUDA 12.4,
`nvcr.io/nvidia/isaac-sim:4.5.0`, kernel 6.5.0-1024-aws. Constants are meaningless
without their environment.

---

## 6. Worked examples (verified; measured constants as of M9)

### 6.1 `minimal.json` on A10G
1 scene, 1 camera, 1 variation, 1280x720, 64 SPP, RGB, budget $50.

- `base_render_s` = 1.51 x (921,600 / 2,073,600) x (64/128) = **0.3356 s**
- modality factor (RGB) = 1.00 -> `per_image_s` = 0.3356 s
- images = 1 -> `scene_s` = 32 + 0.3356 = 32.34 s
- x1.15 = 37.19 s = 0.0103 hr -> x $1.006 = **$0.01** -> **APPROVE**

### 6.2 `multi_scene.json` on A10G
station-a (300x2 = 600 imgs) + station-b (200x1 = 200 imgs), 1920x1080, 128 SPP,
modality factor 1.008 (measured: extra annotators are nearly free), budget $2500.

- `per_image_s` = 1.51 x 1.0 x 1.0 x 1.008 = 1.5221 s
- station-a: 32 + 600 x 1.5221 = 945.25 s; station-b: 32 + 200 x 1.5221 = 336.42 s
- total 1281.66 s x1.15 = 1473.91 s = 0.4094 hr -> x $1.006 = **$0.41** -> **APPROVE**

### 6.3 Same plan, three devices (the generality made concrete)
The identical `multi_scene` plan, costed against each profile through the same code path:

| Profile | GPU-hours | Cost |
|---|---|---|
| T4 | 0.9993 | **$0.53** |
| **A10G** | 0.4094 | **$0.41** |
| H100 | 0.1364 | **$0.45** |

The cost-optimal device is still the **mid-tier A10G**, not the cheapest-per-hour (T4)
nor the fastest (H100) - the punchline survived calibration. The speed/price ratio
matters, and surfacing it is exactly what the governor is for.

### 6.4 Production batch - where governance bites
1 scene, 125,000 variations x 4 cameras = 500,000 images, 3840x2160, 256 SPP,
RGB + DEPTH + 4x annotation modalities (measured factor 1.009), A10G, budget $1000.

- `per_image_s` = 1.51 x 4.0 (4K) x 2.0 (256/128) x 1.009 = 12.189 s
- total = 32 + 500,000 x 12.189 = 6,094,392 s; x1.15 = 1946.8 GPU-hours
  -> x $1.006 = **$1,958.50**
- vs budget $1000 -> **BLOCK / MODIFY** (the gate's job in 2.5/2.6)

Costs reach the range that justifies a governor only at production scale - the realistic
FinOps dynamic. Fixed overhead dominates tiny jobs; variable render cost dominates large
ones. (Note the measured-modality finding softens 6.4 slightly vs the original estimate:
the old 1.23 modality factor overstated annotation cost ~20%; the job still blocks.)

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
