# Plan Schema - Design Specification

> The `GenerationPlan` is the contract between the fuzzy world (the LLM planner) and the
> deterministic world (cost estimator + gates). It is built bottom-up from leaf value
> objects to the top-level plan, with strict validation at every layer.
>
> **Status:** Accepted - **Milestone:** M1 (extended in the M4 training-value pivot)

## 1. Principles

- **Strict boundary.** Every model inherits `StrictModel` (`extra="forbid"`) - unknown
  fields are rejected, not silently dropped. A malformed plan fails validation loudly.
- **Validate by responsibility.** Field constraints guard single values; `model_validator`
  guards cross-field consistency and lives on the model that owns the data.
- **Shape and consistency only.** The schema validates structure, not affordability,
  plausibility, or training-value - those are the gates' jobs.

## 2. Enums

- **`OutputModality`**: RGB, DEPTH, SEMANTIC_SEGMENTATION, INSTANCE_SEGMENTATION, BBOX_2D,
  BBOX_3D, SURFACE_NORMALS, POSE.
- **`RendererType`**: PATH_TRACED, RASTERIZED.

## 3. Leaf models

**`Transform`** - a placement in 3D. `translation`, `rotation` (Euler degrees), `scale`
(validator: all components > 0).

**`AssetReference`** - `asset_id`, `usd_path` (validator: ends `.usd`/`.usda`/`.usdc`),
`transform`, optional `category`.

**`Camera`** - `camera_id`, `transform`, `fov_degrees` (0 < fov < 180).

**`RenderSettings`** - `width`/`height` (0 < x <= 8192), `samples_per_pixel` (0 < x <= 1024),
`renderer` (validator: RASTERIZED must use samples_per_pixel = 1).

**`Budget`** - `max_usd` (> 0), `currency`.

## 4. Randomization block (added in the M4 pivot)

Optional per-scene declaration of what varies across variations. Consumed by the diversity
gate (M4) to estimate coverage efficiency before spend. Backward-compatible: plans without
it are still valid.

**`RandomizationParameter`**

| Field | Type | Rule |
|---|---|---|
| `name` | str | non-empty |
| `levels` | int | >= 1; count of distinct values sampled along this axis |
| `min_value` | float \| None | optional continuous-range floor (for a future domain-gap axis) |
| `max_value` | float \| None | optional; validator: if both present, min < max |

**`Randomization`**

| Field | Type | Rule |
|---|---|---|
| `parameters` | list[RandomizationParameter] | min_length 1; validator: names unique |

## 5. Composite model - `Scene`

| Field | Type | Rule |
|---|---|---|
| `scene_id` | str | non-empty |
| `environment` | AssetReference | required |
| `assets` | list[AssetReference] | min_length 1; validator: unique asset_ids |
| `cameras` | list[Camera] | min_length 1; validator: unique camera_ids |
| `variation_count` | int | >= 1 |
| `randomization` | Randomization \| None | optional (see section 4) |

## 6. Top-level model - `GenerationPlan`

| Field | Type | Rule |
|---|---|---|
| `plan_id` | str | non-empty |
| `request_text` | str \| None | optional original NL request |
| `scenes` | list[Scene] | min_length 1; validator: unique scene_ids |
| `modalities` | list[OutputModality] | min_length 1; validator: no duplicates |
| `render_settings` | RenderSettings | required |
| `budget` | Budget | required |
| `created_at` | datetime | default: timezone-aware now (UTC) |

## 7. Design decisions

1. **`StrictModel` base** (`extra="forbid"`) - the schema is a hard boundary.
2. **USD path validation on `AssetReference`** - catch bad references at parse time.
3. **Renderer/sample consistency** enforced on `RenderSettings`.
4. **Timezone-aware `created_at`** - auditable, unambiguous timestamps.
5. **Randomization: ADDED (M4 pivot).** Originally deferred ("model only
   `variation_count`"); un-deferred when diversity gating became the headline axis, because
   the diversity check needs to know what varies to estimate coverage. Added as an optional,
   backward-compatible block. See `docs/diversity-model.md`.

## 8. Fixtures

`fixtures/plans/valid/` (including `with_randomization.json`) and
`fixtures/plans/invalid/` (one broken rule per file, folder name = expectation). Tests
auto-discover both and assert parse / reject, plus right-reason checks for invalid cases.
