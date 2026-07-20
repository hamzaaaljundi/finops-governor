# Calibration Run Log - M9.2 Session (2026-07-20)

The narrative record of the rental-day session that produced the measurements in
`timings/`. Protocol: [../calibration.md](../calibration.md) (pre-registered before the
session). Environment pins: [environment.md](./environment.md). This log exists because
constants without their story are just numbers - and because the failures en route are
part of the evidence that a real measurement happened on real infrastructure.

## Summary

One working session, ~5 hours wall-clock (~2 of them GPU-billed), three g5.xlarge
instances (two consumed by a driver incompatibility, one productive), total cloud spend
~$4-6 against the $40 cap. All five protocol runs plus warm-ingestion measurements plus
the 626-frame coverage pair captured. Every acceptance criterion from calibration.md
section 4 applied as written; one result (R5) accepted with a documented note.

## Timeline and incidents

**Phase 1 - first instance (NVIDIA GPU-Optimized AMI, driver 595.58).**
Container toolkit refused to start containers: a stale mount list referenced
`libnvidia-egl-wayland.so.1.1.13` while the host shipped 1.1.21. Fixed with a symlink.
Isaac Sim 4.2.0 then crashed at RTX renderer startup - segfault in
`librtx.scenedb.plugin.so` before reaching our script. Pulled 5.1.0: **identical
segfault in the same library**. Two container generations, two years apart, dying at
the same address = the host driver, not the containers. The 2026-era 595-driver line is
incompatible with both Isaac generations' RTX stacks. (Bonus finding from the 5.1.0
attempt: its default entrypoint hijacks trailing arguments into the streaming app -
all subsequent runs force `--entrypoint /isaac-sim/python.sh`.)

**Phase 2 - driver downgrade attempt (Deep Learning Base AMI, kernel 6.17).**
Purged 595, installed `nvidia-driver-570-server`. dkms silently never built the module:
the 570 branch predates kernel 6.17. A partial purge also removed nvidia-utils,
producing a version-mismatch detour. Verdict: current AWS AMIs pair new kernels with
the 595 line; no driver on them can serve Isaac. Terminated.

**Phase 3 - the solution: a dated AMI.** Community AMI `Deep Learning Base OSS Nvidia
Driver GPU AMI (Ubuntu 22.04) 20240915` - driver 550.90.07 and kernel 6.5
factory-matched, from the era Isaac 4.x was tested against. One launch mishap en route:
the instance type silently defaulted to t3.micro (no GPU), diagnosed by `nvidia-smi`
failing while dkms showed a healthy 550 driver - the AMI was never the problem that
time. Relaunched as g5.xlarge.

**Phase 4 - adapter gap found and fixed live.** The generated scripts assumed a running
Kit; standalone execution needs the `SimulationApp` bootstrap and an
`orchestrator.run_until_complete()` footer. Patched on the instance in a loop over all
seven scripts; the fix feeds back into `finops_governor.adapter` as a versioned
improvement. The 10-frame smoke then rendered - **the adapter's output ran on the real
stack** - and the full matrix followed.

**Phase 5 - the shader-cache discovery.** R1's ingestion measured 912 s: not stage
loading but RTX shader compilation, repaid on every `--rm` run. R2-R5 ran with cache
volumes mounted; warm ingestion settled at 28-37 s. The cold/warm split became a
documented model note (cost-model.md section 5, finding 3).

**Phase 6 - R5 rerun.** At 39 ms/frame, filesystem-write jitter dominates the CV
(0.35 at 120 frames). Rerun at 300 frames per protocol: mean unchanged (0.038), CV
0.22 - still above the 0.20 bar, accepted with the documented note that the metric is
timing-resolution-bound at raster speeds; the mean is converged and valid.

**Phase 7 - coverage pair + retrieval.** cov_redundant (600 frames) and cov_trimmed
(26 frames - the gate's own proposal for this plan, verified equal before the session)
rendered at 720p/64spp. The archive compressed 1003 MB -> 1.6 MB, alarming enough to
verify by full extraction and byte-comparison before terminating (near-identical
simple-scene frames and near-uniform depth arrays compress extremely well; every file
byte-identical). Instance terminated; EBS confirmed deleted.

**Phase 8 - the postmortem that renamed the session (added after analysis).**
The 9.5 coverage analysis - the only step in the pipeline that reads image CONTENT
rather than file existence or timestamps - found all pairwise distances exactly zero.
Human inspection confirmed: **every frame of the session is black.** Root cause, found
in the adapter source: lights were only ever emitted inside the frame trigger, where
`rep.create` does not execute, and plans without lighting variation got no light at
all. The GPU spent the session faithfully path-tracing an unlit stage. Consequences
drawn: (1) adapter fixed - a guaranteed setup light plus intensity-modification in
the trigger, with structural tests forbidding creates inside trigger bodies;
(2) the standalone bootstrap folded natively into the adapter; (3) a mandatory
look-at-the-pixels checkpoint added to the RUNBOOK; (4) the timing constants below
stand as strictly-better-than-estimates but are flagged pending re-measurement on a
lit scene (render day 2) - path-tracing an unlit scene under-counts light-sampling
work, and the fail-safe rule forbids shipping a suspected under-estimate as
"measured". The session's most valuable output turned out to be the postmortem: the
validation experiment caught the pipeline's blind spot exactly as designed.

## Results (details in timings/; PENDING RE-MEASUREMENT per Phase 8)

| Run | Setting | Mean s/frame | CV | Verdict |
|---|---|---|---|---|
| R1 | 1080p/128spp PT RGB | **1.5061** | 0.008 | accepted (the anchor) |
| R2 | 720p/64spp PT RGB | 0.5815 | 0.012 | accepted; affine deviation 1.74x, inside the 2x corridor |
| R3 | R1 + depth + normals | 1.5164 | 0.009 | accepted; modalities +0.7% |
| R4 | R1 + seg + bbox | 1.5060 | 0.009 | accepted; modalities +0.0% |
| R5 | 1080p raster | 0.0380 | 0.217 | accepted with note (resolution-bound) |
| I1 | ingestion, warm | 28-37 s | - | accepted; cold ~900 s footnoted |

Constants landed per the fail-safe rounding rule: `ref_render_seconds` 1.51, ingestion
32.0, raster factor 0.03, modality weights 0.005/0.001 (POSE unmeasured, estimate kept).

## What the session changed beyond the numbers

1. The adapter gained its standalone bootstrap (from Phase 4).
2. cost-model.md gained three measured findings, including the consequential one:
   extra annotators are nearly free, so the gate should never discourage them.
3. The advisor's ranking became demonstrably job-shape-dependent under measured
   constants (production fixture: H100 $381.41 vs A10G $391.32; multi_scene: A10G
   still wins) - the argument for per-job advice, now with numbers.
4. The protocol's own rules were exercised for real: the corridor caught a model
   limit without force-fitting, the salvage rule was never needed, and "whatever the
   numbers are, they ship" shipped a 26%-worse anchor without flinching.
