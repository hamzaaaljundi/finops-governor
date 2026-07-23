# ADR 0009 - Session-3 recalibration: lit-scene constants supersede session 2

**Status:** Accepted (supersedes the session-2 values in hardware_profiles.json;
amends cost-model.md section 5); amended 2026-07-21, r5 warm-up re-analysis

## Context

The M9.2 calibration session (2026-07-20) executed the protocol in
docs/calibration.md and shipped measured constants (a10g ref_render_seconds 1.51).
The same session surfaced the black-frame defect: the adapter emitted the scene's
only light inside the frame trigger, where `rep.create` does not execute - so the
measured frames rendered unlit. Timing black frames is still valid timing, but
path tracing an unlit scene does almost no work (no light sampling, no bounces),
so the session-2 constants systematically understated real render cost. The
adapter was fixed (versioned in tests: light created before the trigger), and
session 3 (2026-07-21) re-ran the full matrix on lit scenes under the identical
pinned environment.

## Decision

1. **a10g constants are replaced by session-3 lit measurements:**
   ref_render_seconds 1.51 -> 3.5897 (r1, CV 0.051), fixed_ingestion_seconds
   32.0 -> 38.46 (r1). The lit/unlit correction ratio is 2.3773.
2. **A new profile field, `annot_ingestion_extra_seconds`** (+14.72 on a10g,
   measured as r4 - r1: 53.18 - 38.46). Session 3 showed annotation modalities
   cost ingestion time, not per-frame render time (r4 per-frame equaled r1 within
   noise) - a structurally different result than the modality-weight model
   anticipated, charged as a per-scene fixed term. Profiles where it is
   unmeasured omit the key and take the schema default 0.0; omission (not an
   explicit 0.0) is deliberate - it distinguishes "unmeasured" from "measured
   zero."
3. **t4 and h100 ref_render_seconds are scaled by 2.3773** (t4 3.8 -> 9.03,
   h100 0.45 -> 1.07) and remain marked extrapolated. Leaving them at unlit-
   derived values next to a lit-measured a10g would silently mix provenances and
   corrupt the advisor's cross-device ranking; scaling preserves relative ratios.
   fixed_ingestion_seconds is set flat to 38.46 on all three (ingestion is
   dominated by app start + stage load, not GPU class; previously flat 32.0).
4. **rasterize_factor stays 0.03.** Session 3 measured 0.020 (r5: 0.072 s/frame
   vs 3.5897) but r5 failed the protocol's stability criterion (CV 0.57 with 50
   warm-up frames discarded; likely timing-resolution-bound at 0.07 s/frame, as
   session 2 also documented). Per the protocol, an unstable run does not ship a
   constant. Re-analysis with a wider warm-up window is an open follow-up; the
   retained 0.03 is conservative (fail-safe: over-predicts raster cost).
5. **r2 (affine scaling check) is excluded from constants:** CV 0.2264 failed
   the stability criterion. Its mean (1.0694 s) would test the affine
   prediction, but one unstable run is not evidence either way. A rerun was
   considered and skipped on cost grounds; the exclusion stands on a single
   documented data point.

## Environment

g5.xlarge (us-east-1), NVIDIA A10G (VBIOS 94.02.75.00.01), driver 550.90.07,
kernel 6.5.0-1024-aws, container nvcr.io/nvidia/isaac-sim:4.5.0 @
sha256:c2f47dc82a7714af08d3766efe80ac9d084c2b37b5d0dfbd074797ec56390fc7,
headless, caches volume-mounted. Full capture: docs/calibration/provenance.txt.
The coverage pair (600 + 26 frames, lit, first-frame means 203.87) rendered
without the OptiX denoiser mount - cosmetic only; coverage counts combinations,
not pixels.

## Consequences

- Every pinned dollar value downstream (cost-model.md section 6, the pinned
  estimator/CLI/advisor tests, the README headline figures) is re-derived from
  the new constants via the 9.3 sweep machinery - never hand-edited.
- Whether the section 6.3 punchline ("the mid-tier card wins") survives uniform
  rescaling is an output of the sweep, not an assumption; if it flips, the doc
  reports the flip.
- The gpu.py cost model gains the annot-ingestion term (fixed =
  fixed_ingestion_seconds + annot_ingestion_extra_seconds when annotation
  modalities are present); doc and code land together.
- The protocol's clause 4 ("whatever the numbers are, they ship") was exercised
  twice: session 2 shipped 1.51 in good faith; session 3 shipped 3.5897 when the
  defect was found and fixed. Calibration remains falsifiable, which is the
  point.

## Amendment (2026-07-21): r5 warm-up re-analysis closes the open follow-up

Decision 4's open follow-up - re-analyzing r5 with a wider warm-up window - was run at
`--warmup 100` (double the original 50, on the same already-300-frame run the
protocol's own stability clause calls for). Result: CV **worsened**, 0.57 -> 3.6443
(mean essentially unchanged: 0.072 -> 0.0704). A genuine shader/JIT warm-up transient
shrinks under a wider warm-up window; this grew six-fold instead, which rules out
warm-up drift and points at the instrumentation.

Per-frame delta inspection confirms it: of 199 steady-state deltas, 185 are exactly
0.0s and 14 are exactly 1.0s - only two distinct values in the whole steady state.
`extract_timings.py` derives per-frame time from consecutive PNG file **mtimes**
(docstring, and matches its implementation), not from the run logs docs/calibration.md
section 3 specifies as the timing source - a documentation/implementation mismatch
this re-analysis surfaced. At raster's true rate of ~14 frames/second, most
consecutive frames complete inside the same rounded second (delta 0) and roughly
1-in-14 straddle a second boundary (delta 1): 14/199 = 0.0704, matching the reported
mean exactly. Modeling this as a pure Bernoulli process (p = 0.0704, zero real
render-time variance) predicts std 0.2557 and CV 3.635 against the reported 0.2564 /
3.6443 - within rounding. **The instability is fully explained by 1-second mtime
quantization against a sub-0.1-second-per-frame signal; no genuine render-time
jitter is required to produce it.** The mean is not discredited by this (it remains,
in effect, an unbiased boundary-crossing rate estimate), but a per-frame CV computed
on data this coarse is not a meaningful stability measure, and no warm-up window can
fix an instrumentation floor.

**Decision, closed:** `rasterize_factor` stays **0.03** (fail-safe, conservative,
over-predicts raster cost) - not because raster rendering is unstable in the sense the
protocol's stability clause means, but because mtime-based timing cannot resolve a
signal this fast. A future rasterize_factor measurement needs in-app sub-second
timestamp logging (matching what section 3 already specifies as the intended source)
or a batched-timing design (time N frames, divide), not per-frame mtime deltas. This
is now a documented limitation of the measurement method, not an open question about
the render itself.

## Note (2026-07-22, session 4a): the constant was challenged and rehabilitated

Session 4a briefly appeared to contradict `ref_render_seconds = 3.5897`: two runs on
the reference scene measured ~1.55 s/frame - suspiciously close to session-2's
"unlit" 1.51. The resolution (ADR 0011): those runs WERE unlit - a threefold adapter
regression rendered all-black frames that an alpha-blind pixel gate false-passed. No
lit measurement was made; 3.5897 stands, and session 3's preserved lit frames remain
its ground truth. Separately, session 4a measured an unlit raster/pathtraced ratio of
0.0246 (mean stable across warm-up windows; per-frame deltas properly sub-second on
that box, unlike this session's 1s mtime floor - the floor is environment-dependent).
Whether the unlit ratio transfers to the lit regime is unknown; **0.03 stays**, and a
lit re-measurement belongs to session 4c.

**Session-4c update (same day):** the lit re-measurement happened - lit raster
0.0715 s/frame against a same-day lit reference of 3.5329 gives 0.0202 (0.0199
against this ADR's 3.5897). With session-3 r5's ~0.020, the factor is now
triple-corroborated at ~0.02; 0.03 is retained as fail-safe rounding. The
follow-up this amendment opened is closed with data. Details:
docs/calibration.md section 8.2.
