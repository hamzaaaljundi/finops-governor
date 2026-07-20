# Geometric Validity Model - Design Specification

> The design-on-paper artifact for **M5, Task 5.2**. Defines the geometric invariants the
> USD validity axis checks, the finding and severity each produces, and the honest limits
> of the bounding-box approach. Implementation (Task 5.4) transcribes this spec.
>
> **Status:** Accepted - **Milestone:** M5 - **Consumed by:** the Governor (as a validity axis)

---

## 1. The problem this axis exists to catch

A generation job can be affordable and well-diversified and still produce garbage: the
scene itself is broken. An asset reference that does not resolve, a robotic arm authored a
meter through the concrete floor, an asset floating outside the environment, a camera
aimed at a blank wall - each renders thousands of useless frames before anyone notices.

This axis validates the **scene description** (the USD stage) before any render - never
the output pixels - preserving the block-before-GPU-spend guarantee.

## 2. The checks

Four checks, each a pure read over the loaded stage. Severity follows one principle: a
defect that corrupts the data is BLOCKING; a defect that is plausibly intentional or
merely wasteful is WARNING.

| # | Check | Question | Severity | Rationale |
|---|---|---|---|---|
| 1 | Asset existence | Does every referenced USD path resolve and open? | **BLOCKING** | A missing asset cannot render; the scene is unbuildable. |
| 2 | Asset-vs-environment collision | Does any asset penetrate the environment beyond tolerance? | **BLOCKING** | The environment (floor, walls) is the immovable ground-truth frame; penetration means the authoring is broken and the data will be garbage. |
| 3 | Asset-vs-asset collision | Do two assets interpenetrate beyond tolerance? | **WARNING** | Contact-rich scenes (grasping, tool-on-bench) legitimately have near-contact and minor interpenetration; flag, do not block. |
| 4 | Camera framing | Is the camera oriented toward the scene at all? | **WARNING** | A camera aimed away renders blank frames - wasteful, but conceivably a deliberate composition; flag, do not block. |

The environment/asset severity split is anchored to the schema, not a heuristic: check 2
tests `Scene.assets` against `Scene.environment`; check 3 tests `Scene.assets` pairwise.
The distinction is structural in the plan contract.

## 3. The math (verified against usd-core 26.5)

### 3.1 Bounding boxes

All geometry checks operate on **world-space axis-aligned bounding boxes** (AABBs),
computed via `UsdGeom.BBoxCache.ComputeWorldBound(...).ComputeAlignedRange()`.

### 3.2 Collision with a resting tolerance (checks 2 and 3)

Naive AABB overlap would flag every object *resting on* the floor (their boxes touch).
The check therefore measures **penetration depth** - the shallowest-axis overlap - and
fires only beyond a tolerance:

```
overlap_i         = min(a_max[i], b_max[i]) - max(a_min[i], b_min[i])   for i in x,y,z
penetration_depth = 0            if any overlap_i <= 0   (no intersection)
                  = min(overlap) otherwise
finding fires when penetration_depth > epsilon            (default epsilon = 0.01 m)
```

Verified: a cube resting exactly on the floor measures 0.0 (no finding); a cube sunk
through it measures > epsilon (finding).

### 3.3 Camera framing proxy (check 4)

A deliberately coarse **orientation** check - not frustum visibility:

```
forward   = camera local -Z rotated by the camera's Euler rotation   (USD convention)
to_scene  = normalize(scene_center - camera_position)
dot       = forward . to_scene
finding fires when dot <= 0        (camera pointing away from the scene entirely)
```

`scene_center` is the centroid of all asset AABB centers. Verified: a camera aimed at the
scene scores +0.995; the same camera rotated 180 degrees scores -0.995.

## 4. Locked decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Collision severity split | env = BLOCKING, asset-asset = WARNING | Environment is the immovable frame; asset contact is often intentional. Anchored to `Scene.environment` vs `Scene.assets`. |
| 2 | Resting tolerance | epsilon = 0.01 m (tunable) | Touching is not clipping; only true penetration fires. |
| 3 | Framing method | Dot-product orientation proxy, WARNING | The full frustum is unbounded in depth; a finite "camera box" needs an arbitrary far plane (false precision). The dot product catches the failure that matters (aimed away) with one honest operation. |
| 4 | Stage source (M5) | One hand-authored `.usda` per scene fixture | The validity check takes a stage and validates it, regardless of how it was born. |
| 5 | Plan-driven stage assembly | Deferred to the plan-to-USD boundary - **crossed at M9** (`finops_governor.adapter`: plan -> runnable Replicator script) | Assembling stages from `AssetReference`s (references, xformOp conversion, up-axis) is composition engineering, not validity logic. Documented boundary, not a shortcut. |

## 5. Scope and assumptions (read this)

Deliberately simplified, with the limits stated:

1. **AABB, not mesh-level.** Boxes overestimate rotated or concave shapes; a diagonal rod
   near a wall may flag without true mesh contact. This catches gross authoring errors,
   not fine interpenetration - the errors that matter at gate time.
2. **Penetration depth is the shallowest-axis overlap.** It detects penetration beyond
   tolerance; it does not report the full sink depth (a 0.7 m sink through a 0.1 m slab
   measures 0.1 - still far above epsilon, still fires).
3. **Framing is orientation-only.** No field-of-view, no occlusion, no partial-framing
   detection. A camera can pass the check and still frame the scene poorly; it cannot pass
   while pointing away from it.
4. **Static scenes at default time.** Bounds are evaluated at `TimeCode.Default()`;
   animated clips are out of scope.

**What a production version would need:** convex-hull or mesh-level collision for tight
tolerances; true frustum-visibility (or a render-free coverage estimate) for framing;
time-sampled evaluation for animated scenes.

The composition is the point, not the geometry: these are standard scene-lint checks made
valuable by sitting in one gate beside cost and training-value - three reasons not to
spend, one decision.
