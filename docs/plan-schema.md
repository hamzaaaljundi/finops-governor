# Plan Schema — Design Specification

> The design-on-paper artifact for **M1**. This document defines *what a generation
> plan is* before any Pydantic code is written. When building the models (Task 1.3),
> this spec is the reference — implementation should be transcription, not invention.
>
> **Status:** Accepted · **Milestone:** M1 · **Implements the contract for:** M2, M3, M4, M5

---

## 1. Responsibility

`GenerationPlan` has one job: **describe a synthetic-data job to be done, plus the
budget constraint it must respect.** Nothing else.

It is the **input** to the pipeline. It is the boundary between the fuzzy world
(natural language, the LLM) and the deterministic world (cost estimator, gates).
The LLM's messy output is forced through this contract, and only schema-valid plans
are allowed to exist downstream.

---

## 2. Design principle — design backwards from the consumers

The schema is designed backwards from what its **deterministic consumers** need, not
forwards from "what does a job have." There are exactly three consumers:

| Consumer | Milestone | What it needs from the plan |
|---|---|---|
| **Cost estimator** | M2 | Everything that drives GPU spend: image count, resolution, render quality, modality count |
| **Budget gate** | M2 | The budget ceiling |
| **Validity gate** | M3 | Everything geometric: asset references, placements, camera positions |

Every field in this spec exists because at least one consumer reads it. If a field
serves no consumer, it is cut.

---

## 3. The boundary — what the plan must NOT contain

The plan is the pipeline's **input**, so it must never contain the pipeline's **outputs**:

- **No estimated cost / GPU-hours.** That is what M2 *computes from* the plan. The plan
  carries the budget *ceiling* (a constraint), never the estimate (a result).
- **No verdict** (approve / modify / block). That is the gate's output.
- **No validity findings.** That is M3's output.
- **No pricing table.** That is estimator configuration, not part of any single job.
- **No rendered output** (pixels, output file paths). The entire premise is that we
  decide *before* rendering.

Everything that is a *result* lives in a separate object produced by the component that
computes it. Holding this line keeps the plan a clean description of intent.

---

## 4. Locked design decisions

These five forks were decided during design and are fixed for M1:

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Rotation representation | **Euler angles, degrees** | Human-readable for hand-authored fixtures; gimbal-lock edge cases accepted and noted |
| 2 | Variation count scope | **Per-scene** | More flexible; makes the cost summation clean |
| 3 | Temporal data | **Stills only** for M1 | Video/frame-sequences multiply complexity across every downstream component; deferred |
| 4 | Target GPU | **Not in the plan** | Estimator assumes a default GPU; keeps the plan clean; trivial to add later |
| 5 | Randomization detail | **Only `variation_count`** | The *count* of variations is all cost and validity need; modeling *what* varies is a future DSL |

---

## 5. Model hierarchy (bottom-up)

Build order for Task 1.3: leaves first (depend on nothing), then composites, then the
top-level type. This ordering means each model is complete and testable before anything
depends on it.

### 5.1 Leaf models

#### `Transform` — a placement in 3D space
Reused by both assets and cameras.

| Field | Type | Required | Constraint | Purpose |
|---|---|---|---|---|
| `translation` | tuple[float, float, float] | no — default `(0,0,0)` | — | Position; M3 uses it for bounds/collision checks |
| `rotation` | tuple[float, float, float] | no — default `(0,0,0)` | euler degrees | Orientation |
| `scale` | tuple[float, float, float] | no — default `(1,1,1)` | each component `> 0` | Size; scale ≤ 0 is invalid geometry |

#### `AssetReference` — a pointer to a USD asset plus its placement

| Field | Type | Required | Constraint | Purpose |
|---|---|---|---|---|
| `asset_id` | str | **yes** | non-empty | Identity; needed for instance segmentation and readable validity errors |
| `usd_path` | str | **yes** | non-empty, ends `.usd` / `.usda` / `.usdc` | Where M3 loads geometry from |
| `transform` | Transform | no — default identity | — | Placement in the scene |
| `category` | str | no | — | Semantic label for segmentation |

#### `Camera` — a viewpoint
Camera count is a direct cost multiplier (more cameras = more images per variation).

| Field | Type | Required | Constraint | Purpose |
|---|---|---|---|---|
| `camera_id` | str | **yes** | non-empty | Identity |
| `transform` | Transform | **yes** | — | Position/orientation; M3 checks it frames the scene |
| `fov_degrees` | float | no — default `50` | `0 < fov < 180` | Framing |

#### `RenderSettings` — quality/size knobs (the main cost drivers)

| Field | Type | Required | Constraint | Purpose |
|---|---|---|---|---|
| `width` | int | **yes** | `> 0`, `<= 8192` | Cost driver + output size |
| `height` | int | **yes** | `> 0`, `<= 8192` | Cost driver |
| `samples_per_pixel` | int | no — default `64` | `>= 1`, `<= 1024` | Path-trace quality; a **major** cost driver |
| `renderer` | enum `{PATH_TRACED, RASTERIZED}` | no — default `PATH_TRACED` | — | Quality/cost tradeoff |

#### `OutputModality` — an enum
Each additional modality adds render/annotation cost — the multimodal-framing premise
made concrete.

Values: `RGB`, `DEPTH`, `SEMANTIC_SEGMENTATION`, `INSTANCE_SEGMENTATION`,
`BBOX_2D`, `BBOX_3D`, `SURFACE_NORMALS`, `POSE`.

#### `Budget` — the constraint the gate enforces

| Field | Type | Required | Constraint | Purpose |
|---|---|---|---|---|
| `max_usd` | float | **yes** | `> 0` | The ceiling M2's budget gate checks against |
| `currency` | str | no — default `"USD"` | — | Kept simple for M1 |

### 5.2 Composite model

#### `Scene` — one 3D setup and how many randomized variations to produce

| Field | Type | Required | Constraint | Purpose |
|---|---|---|---|---|
| `scene_id` | str | **yes** | non-empty | Identity |
| `environment` | AssetReference | **yes** | — | The backdrop (e.g. the assembly floor) |
| `assets` | list[AssetReference] | **yes** | length `>= 1` | The subjects (e.g. the arm, props) |
| `cameras` | list[Camera] | **yes** | length `>= 1` | Viewpoints; count multiplies image count |
| `variation_count` | int | **yes** | `>= 1` | How many randomized variations to render |

### 5.3 Top-level model

#### `GenerationPlan` — the object the whole system passes around

| Field | Type | Required | Constraint | Purpose |
|---|---|---|---|---|
| `plan_id` | str | **yes** | non-empty | Identity for the audit trail |
| `request_text` | str | no | — | Original NL request, preserved for auditing |
| `scenes` | list[Scene] | **yes** | length `>= 1` | The actual work |
| `modalities` | list[OutputModality] | **yes** | length `>= 1`, no duplicates | What to capture per image |
| `render_settings` | RenderSettings | **yes** | — | Global quality/size |
| `budget` | Budget | **yes** | — | The constraint |
| `created_at` | datetime | no — default `now()` | — | Audit timestamp |

Keep `GenerationPlan` **dumb**: it holds structure, not behavior. Gates decide verdicts;
the estimator computes cost; the plan only *describes* the job.

---

## 6. Completeness check — tracing fields to consumers

### Cost model (M2) preview

```
total_images   = Σ over scenes of ( variation_count × number_of_cameras )
per_image_work ∝ width × height × samples_per_pixel × modality_weight(modalities)
gpu_hours      = total_images × per_image_work / throughput
cost_usd       = gpu_hours × price_per_hour
```

Every variable on the right maps to exactly one schema field —
`variation_count`, `cameras`, `width`, `height`, `samples_per_pixel`, `modalities`.
That one-to-one trace is the proof the schema is **complete for M2**.

### Validity checks (M3) preview

Every geometric check maps to `usd_path` (load the asset), `transform` (where it sits),
and `cameras` (whether the viewpoint frames the scene). Complete for M3.

---

## 7. Invariants (become validators in Task 1.5)

Field-level constraints (Section 5) catch bad individual values. These model-level
invariants catch bad *combinations* — the rules involving more than one field:

- `modalities` contains no duplicates.
- If `INSTANCE_SEGMENTATION` is requested, every `AssetReference` must have a stable
  `asset_id` (already required, so this is a consistency assertion).
- Every `scene_id`, `asset_id`, and `camera_id` is unique within its collection.
- `RASTERIZED` renderer with a very high `samples_per_pixel` is contradictory
  (samples are a path-tracing concept) — flag or normalize.

> Encode only rules that are genuinely about plan **validity**. Budget checks belong to
> M2's gate; geometry checks belong to M3's gate. The schema validates *shape and
> internal consistency*, not *affordability* or *physical plausibility*.

---

## 8. Deferred (explicitly out of scope for M1)

Recorded so the boundaries are deliberate, not forgotten:

- **Temporal / video sequences** (frame ranges, motion) — decision #3.
- **Target GPU selection** in the plan — decision #4.
- **Domain-randomization DSL** (which attributes vary, ranges, seeds) — decision #5.
- **Quaternion rotations** — decision #1.
- **Multi-currency budgets** with conversion.

Each is an additive extension that does not change the M1 contract's core shape.
