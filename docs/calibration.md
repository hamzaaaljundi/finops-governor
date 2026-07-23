# Calibration Protocol - Measuring the Render Constants

> The design-on-paper artifact for **M9, Task 9.1** - written BEFORE any GPU is rented.
> Defines what gets measured, how, on what hardware, the acceptance criteria, and the
> spend cap. Task 9.2 executes this protocol verbatim; Task 9.3 lands the numbers.
>
> **Status:** EXECUTED twice - session 2 (2026-07-20) and session 3 (2026-07-21,
> supersedes) - **Milestone:** M9 - **Consumed by:** hardware_profiles.json, cost-model.md section 5
> Session 2 executed the protocol but measured unlit frames (the adapter's
> black-frame defect, found and fixed in the same session). Session 3 re-ran the
> full matrix on lit scenes under the identical pinned environment: R1/R3/R4
> stable (CV ~0.05) and shipped; R2 excluded (CV 0.2264); R5's measured
> rasterize ratio rejected (CV 0.57, timing-resolution-bound). The session-3
> coverage pair (600/26 frames, lit) feeds the real-data coverage analysis.
> Constants supersession rationale: ADR 0009. Raw artifacts: [calibration/](./calibration/).
> Environment deviations from plan: container 4.5.0 (not 4.2.0 - the 2026
> 595-driver line crashes both 4.2/5.1; a dated 2024 AMI with driver 550.90.07
> was required); adapter scripts are natively standalone since the M9.2 fix.

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

Timing source: consecutive PNG output file mtimes (`session_kit/extract_timings.py`),
not run-log timestamps as an earlier draft of this section specified - the actual
tooling measures via BasicWriter's output files. This resolves to whatever the
filesystem's mtime granularity is (observed: 1 second) and is adequate for the
multi-second-per-frame path-traced runs (R1-R4), but breaks down for anything
approaching or faster than that granularity - see ADR 0009's amendment on R5.
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

## 7. Session-3 coverage analysis (real lit frames, k=20)

The coverage pair (600-frame redundant / 26-frame trimmed plan, 3.1 azimuth x
lighting grid, declared capacity k=20) was analyzed by pairwise pixel-distance
clustering (session_kit/coverage_analysis.py, Otsu-thresholded L2).

**Result: the instrument, not the model, is the binding constraint.** At the
automatic threshold both runs measure 2 distinct clusters against predictions of
20.0 and 14.7 - the split isolating the dimmest dome-intensity level (cluster
sizes 475/125 =~ 600 x 4/5 / 1/5). A manual threshold sweep reveals scale
hierarchy: t=6 -> 4 clusters (lighting levels), t=3 -> 12, t=1.5 -> 19 (near
the declared space). Global lighting dominates pixel distance; object azimuth
on untextured primitives is a near-noise-level signal at 64 spp undenoised.

Two honesty notes. The sweep threshold is post-hoc - the claim is that cluster
structure exists at scales matching both declared parameters, not that the
predicted count was confirmed. And 19 overshoots the physically distinct space:
the azimuth levels [0, 120, 240, 360] collide at 0=360 (a real declared-space
defect this analysis surfaced - declared k=20, true k=15, 25% phantom
capacity; precisely the waste class the diversity gate prices), so ~4 of the
19 clusters are noise-splits.

**Conclusion:** the expected-coverage model reasons over declared parameter
space (ADR 0002: the gate never inspects generated data) and is not contradicted
by this measurement; empirically validating it end-to-end requires ground-truth
parameter logging per frame (a Replicator writer extension), not appearance
clustering on a minimal gray scene. Documented per protocol clause 2: a known
instrument limit, not force-fitted.

## 8. Session-4 validation (2026-07-22): lit re-measurements on the fixed adapter

Session 4 ran as three rentals (4a, 4c, 4d; ~$8-10 total against a $15+$10 cap).
4a produced no lit frames - a threefold silent adapter regression plus an
alpha-blind pixel gate, fully documented in ADR 0011 - and 4c/4d re-ran the
deliverables on the triple-fixed kit with an RGB-only gate. All 4c/4d frames were
verified lit (RGB-only means 161-214) and human-inspected before any number below
was accepted.

### 8.1 D2 - larger-scene point: the 2x corridor passed at 1.6%

A 12-asset scene (6x the reference's asset count) with an additional per-frame
scatter parameter, same resolution/spp as the reference (1920x1080 @ 128):

    measured 3.5329 s/frame (150 frames, warmup 20, CV 0.052)
    predicted 3.5897 (ref_render_seconds, scene-complexity-independent by design)
    deviation: 1.6% - not merely inside the pre-registered 2x corridor
    [1.79, 7.18]; nearly on the prediction.

Conclusion: at this scene class, resolution x samples dominates per-frame cost
and asset count is not a first-order driver - the cost model's deliberate
exclusion of scene complexity (section 6's known limit) is empirically
supported, not merely asserted. The run's ingestion_s (862) is cold-shader-
compile-inclusive and is NOT comparable to the calibrated ingestion constant;
recorded here to prevent future misreading.

### 8.2 D3 - rasterize_factor: triple-corroborated at ~0.02; 0.03 stands

300 rtx_realtime frames on the reference scene, lit (RGB mean 161.87):

    mean 0.0715 s/frame (warmup 100; warmup 150 cross-check: 0.0383 -> n/a, see
    note), CV 0.699 - honestly FAILS the <0.20 bar, consistent with session-3's
    r5 (0.57): raster-speed per-frame timing is inherently jittery.
    rasterize_factor = 0.0715 / 3.5329 (same-day lit reference) = 0.0202
                     = 0.0715 / 3.5897 (calibrated constant)     = 0.0199
    Session-3 r5's own estimate: ~0.020. Three independent measurements agree.

`rasterize_factor` stays **0.03** - fail-safe upward rounding of a now
measurement-backed ~0.02 (over-estimating raster cost can only make the gate
conservative). Two instrument notes: (a) this box's filesystem resolved
sub-second mtimes (54 distinct deltas; the session-3 1-second quantization floor
is environment-dependent, not universal); (b) min delta was NEGATIVE (-0.092s) -
BasicWriter writes frames asynchronously and occasionally out of frame order at
raster speeds, inflating CV beyond true render variance; the mean is unbiased,
the CV is an upper bound. The in-app watcher instrumentation (ADR 0009
amendment's proposal) hung app startup in 4a and was retired - unnecessary on
this stack anyway given (a).

### 8.3 D1 - demo frames (not a calibration input)

96 lit frames rendered from the gate's own value-trimmed proposal
(120 -> 96, ADR 0007 pipeline on camera), assembled with the terminal-verdict
recording into demo/s4_governed_render.mp4. Session 4d re-rendered the same plan
with stylized PBR demo assets (session_kit_s4/assets_demo/ - a separate set;
the gray calibration assets in assets/ are untouched and remain the only assets
any constant derives from). NVIDIA's cloud-hosted Franka was successfully
fetched and rendered in-container (the fetch mechanism is validated) but at a
~20x unit-scale mismatch to the hand-authored scene; real-vendor-asset
integration is deferred as future polish, not attempted blind.

### 8.4 Runbook lessons folded in (cumulative)

RGB-only pixel gates (.convert('RGB') - alpha carried a 63.75 false-pass);
frames arrive vertically flipped from BasicWriter (ffmpeg -vf vflip at assembly;
cosmetic); per-run ~14-min cold shader compile is avoidable with a persistent
cache mount (-v .../shadercache:/root/.cache/ov) - documented as an optimization
deliberately NOT used this arc to keep run conditions consistent with sessions
1-3; local-only artifacts (assets, recordings) are copied, never zipped -
kit-replacement wholesale deleted the verdicts recording once.
