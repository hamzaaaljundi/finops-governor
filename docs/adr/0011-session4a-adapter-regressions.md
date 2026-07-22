# ADR 0011 - Session-4a postmortem: a threefold silent adapter regression, an alpha-blind pixel gate, and the frozen kit that wasn't

**Status:** Accepted (fixes landed same-day; guards specified below)

## Context

Session 4a (2026-07-22, two g5.xlarge rentals, ~$5 total) set out to close three
deliverables: the real-frames demo video (D1), a larger-scene calibration point (D2),
and a properly-timed rasterize_factor (D3). It closed none of them as planned - and
produced more durable value than the plan would have, by exposing three latent defects
that only contact with real Isaac Sim could reveal.

## What happened, in discovery order

1. **The smoke test failed with a graph-build error** (`Invalid AttributeObj in
   connectAttr`) that session 3 never saw. Bisecting with the committed session-kit
   "reference" script failed identically - which exposed finding A.
2. **Finding A: the committed `session_kit/` was not frozen session-3 state.** It had
   been regenerated post-session by the then-current adapter (the same drift event
   that had already silently changed the coverage plans' lighting declaration, caught
   earlier). The true on-box session-3 scripts survive only in the gitignored `kit/`
   scratch tree. Every "byte-identical proven script" assumption downstream of the
   commit was false.
3. **Finding B, regression 1 of 3:** the adapter emitted
   `rep.modify.attribute(scene_light, 'intensity', ...)` (object-first); the proven
   session-3 form is `rep.modify.attribute('intensity', ..., input_prims=scene_light)`.
   The regressed form fails Replicator 1.11.35 graph build and renders nothing.
   Fixed on-meter; the re-run wrote 96 frames and "passed" the pixel gate.
4. **Finding C: the pixel gate was alpha-blind.** Checkpoint 2.5 averaged all
   channels of BasicWriter's RGBA output; an all-black frame with opaque alpha
   reports mean 255/4 = 63.75 - comfortably above the >10 bar. Two black runs
   false-passed. The tell that finally exposed it: frames 0 and 95 reporting
   *identical* means across independent runs, and local inspection showing R/G/B
   max 0.0.
5. **Findings D and E, regressions 2 and 3 of 3:** diffing the true session-3
   scripts (whose preserved frames on local disk - 1,412 of them - show RGB means
   ~185-188, i.e. genuinely lit) against the adapter's output exposed two more
   silent regressions: the camera aim (`look_at=(0, 0, 0)` proven vs. Euler
   `rotation=` emitted - framing empty space) and the light itself
   (`Dome, intensity=1000` proven vs. `Sphere, position=(0,4,0), intensity=1500`
   emitted - effectively unlit in Isaac's units). Unlike regression 1, these fail
   SILENTLY: the graph builds, frames are written, every RGB pixel is zero.

## Interpretive consequences (what the black frames un-measured)

- **Session-3's `ref_render_seconds = 3.5897` is rehabilitated.** Session 4a's two
  lit-looking-but-black measurements (~1.55 s/frame) briefly appeared to contradict
  it - matching session-2's "unlit" 1.51 almost exactly. They matched because they
  WERE unlit. No lit measurement was made in session 4a; the session-3 constant
  stands unchallenged, and its preserved lit frames remain the ground truth.
- **The D2 "corridor break" is void.** The bigscene's 1.633 s/frame was measured on
  black frames; no scene-complexity conclusion can be drawn from it. D2 is unrun.
- **D3's rasterize ratio (0.0382/1.5542 = 0.0246) was measured with both numerator
  and denominator in the same black-frame regime.** Whether an unlit raster/pathtraced
  ratio transfers to the lit regime is unknown; `rasterize_factor` stays 0.03
  (conservative, fail-safe) and D3 is re-run lit in session 4c. One genuine keeper
  from the attempt: this AMI/box pair produced sub-second mtime resolution (std
  0.0095s, properly fractional deltas), so the session-3 1-second-quantization floor
  is environment-dependent, not universal - the watcher instrumentation (which hung
  app startup and was abandoned) may be unnecessary on this stack.

## Decision

1. **The adapter emits only empirically proven forms**, matched to the session-3
   scripts verified by their preserved frames: name-first `input_prims=` attribute
   modification; `look_at=(0, 0, 0)` cameras; `Dome, intensity=1000` default light.
   Three tests pin these forms. A string test cannot prove Isaac validity - that
   asymmetry is permanent - but it CAN prevent regression from a form that real
   frames have validated to one that nothing has.
2. **Checkpoint 2.5 is RGB-only.** `.convert('RGB')` before averaging, and the
   known-false-pass value (63.75) is documented in the runbook as the signature to
   distrust. Human-eyes inspection of an scp'd frame happens BEFORE full renders.
3. **Committed calibration artifacts get a checksum manifest.** A
   `session_kit*/MANIFEST.sha256` generated at freeze time and verified by a test;
   regenerating a "frozen" kit then fails CI loudly instead of drifting silently.
   (Applies to scripts and plans; frame outputs stay uncommitted.)
4. **Download-after-each-deliverable is runbook law.** Session 4a's first instance
   was terminated with all outputs onboard; only chat-preserved JSONs survived.
   Batch-download-at-the-end is retired.

## Consequences

- Session 4c (a short, ~45-minute execution of the now-triple-fixed kit) owns the
  original D1/D2/D3 deliverables. Its smoke gate is the fixed, RGB-only checkpoint.
- The M9.4 adapter's tests now encode everything real-GPU contact has taught across
  four sessions: light placement (0009), endpoint collision (0009), signature, light
  type, and camera aim (this ADR). The list is expected to grow; that is the point
  of keeping a GPU-facing seam honest with string tests plus periodic real contact.
- The project's recurring lesson gets a name here: **every constant, script, or
  "frozen" artifact is only as trustworthy as the mechanism preventing its silent
  regeneration.** The dollar-figure drift test (M9.5) guards prose; the manifest
  (decision 3) guards artifacts; real-render smoke gates guard the adapter.
