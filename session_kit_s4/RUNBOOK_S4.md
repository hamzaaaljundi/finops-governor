# Rental-Day Runbook - Session 4 (D1 demo video + D2 bigscene point + D3 raster timing)

Hard cap **$15**; expected ~1.5-2.5 h of g5.xlarge (~$2-3). Set a phone timer at
launch. Environment recipe is session-3-proven: community AMI **Deep Learning Base
OSS Nvidia Driver GPU AMI (Ubuntu 22.04) 20240915** (NOT the NVIDIA GPU-Optimized AMI
- driver 595.xx segfaults), image `nvcr.io/nvidia/isaac-sim:4.5.0`, and the
`nvoptix.bin` mount in every docker run.

## Deliverables and pre-registered acceptance criteria (decided now, not after)

| # | Deliverable | Accept when |
|---|---|---|
| D1 | Real-frames demo video material | 96 frames of `s4_demo` on disk, pixel mean > 10, first+last frame human-checked |
| D2 | Larger-scene calibration point | 150 frames, CV < 0.20 (else extend per protocol clause 1); measured s/frame lands within the **2x corridor** of the model's 3.5897 prediction, or the deviation ships DOCUMENTED as a known model limit (protocol clause 2 - not force-fitted) |
| D3 | rasterize_factor, properly timed | Sidecar shows `distinct_delta_values` >> 2 (the mtime signature was exactly 2); then CV < 0.20 accepts a new measured factor, CV >= 0.20 ships documented as genuine raster jitter - either result closes the ADR 0009 open item |

Whatever the numbers are, they ship.

## 0. Pre-flight (Mac, before renting - all free)

- [ ] `session_kit_s4/` present with: `plans/` (s4_demo_plan, s4_demo_trimmed,
      s4_bigscene), `scripts/` (s4_demo_trimmed.py, s4_bigscene.py,
      s4_raster_timed.py), `extract_sidecar_timings.py`, this runbook
- [ ] Copy the session-3 assets in: `cp session_kit/assets/*.usda session_kit_s4/assets/`
- [ ] Analyzer dry-run passes locally:
      `python3 session_kit_s4/extract_sidecar_timings.py /tmp/fake_sidecar.json --warmup 100`
      (generate the fake sidecar per the note in the analyzer docstring if needed)
- [ ] Record the terminal segment for the video (no GPU needed - can also be done
      after the session):
```bash
cd ~/Desktop/finops-governor
finops-governor session_kit_s4/plans/s4_demo_plan.json
# -> MODIFY: 120 -> 96 (expected-coverage trim) - THE money shot: the governor
#    catching redundancy in its own demo job
finops-governor session_kit_s4/plans/s4_demo_trimmed.json
# -> APPROVE at $0.12 - the gate's own proposal, re-gated, approves (ADR 0007
#    convergence invariant, on camera)
```
Capture with VHS (like `demo/demo.tape`) or plain screen recording - your call.

## 1. Launch (AWS console)
EC2 -> Launch instance: name `finops-s4` | AMI: **Deep Learning Base OSS Nvidia
Driver GPU AMI (Ubuntu 22.04) 20240915** (community AMIs; exact session-3 image) |
Type **g5.xlarge** | your existing key pair | 100 GB gp3 | Launch. Note the IP.
**Start the timer.**

## 2. Connect + upload
```bash
scp -i ~/Downloads/calibration.pem -r session_kit_s4 ubuntu@<IP>:/home/ubuntu/kit
ssh -i ~/Downloads/calibration.pem ubuntu@<IP>
nvidia-smi    # expect driver 550.90.07; record it
mkdir -p /home/ubuntu/kit/out
```

## 3. Pull Isaac Sim
```bash
docker login nvcr.io    # user: $oauthtoken   password: <NGC API key>
docker pull nvcr.io/nvidia/isaac-sim:4.5.0
```

## 4. Smoke + Checkpoint 2.5 (mandatory pixel check)
```bash
cd /home/ubuntu
sed 's/num_frames=96/num_frames=8/' kit/scripts/s4_demo_trimmed.py > kit/scripts/smoke.py
docker run --rm --gpus all -e ACCEPT_EULA=Y \
  -v /home/ubuntu/kit:/kit \
  -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro \
  --entrypoint /isaac-sim/python.sh \
  nvcr.io/nvidia/isaac-sim:4.5.0 /kit/scripts/smoke.py 2>&1 | tee kit/out/smoke.log

python3 -m pip install --user pillow numpy -q
python3 -c "import glob; from PIL import Image; import numpy as np; a = np.asarray(Image.open(sorted(glob.glob('kit/out/s4_demo/**/rgb_*.png', recursive=True))[0]).convert('RGB')); print('RGB-only mean:', round(float(a.mean()), 2))"
```
RGB-only mean > 10 -> proceed. Near 0 -> BLACK FRAMES: STOP, diagnose before any
further spend. **`.convert('RGB')` is mandatory** (session-4a postmortem: BasicWriter
emits RGBA; averaging all four channels reports 63.75 for an all-black frame - the
opaque alpha alone clears the bar - which false-passed two black runs). Also scp one
frame home and open it with human eyes BEFORE the full render, not after. Then clear
the smoke output so D1's frame count is clean: `rm -rf kit/out/s4_demo`

## 5. D1 - demo render (96 frames, ~6-7 min)
```bash
date +%s > kit/out/s4_demo_start.txt
docker run --rm --gpus all -e ACCEPT_EULA=Y \
  -v /home/ubuntu/kit:/kit \
  -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro \
  --entrypoint /isaac-sim/python.sh \
  nvcr.io/nvidia/isaac-sim:4.5.0 /kit/scripts/s4_demo_trimmed.py 2>&1 | tee kit/out/s4_demo.log
ls kit/out/s4_demo/**/rgb_*.png | wc -l    # expect 96
```
Pixel-check the FIRST and LAST frame (same one-liner, both indices), and scp one home
for human eyes.

## 6. D2 - bigscene calibration point (150 frames, ~10-15 min if model holds)
```bash
date +%s > kit/out/s4_bigscene_start.txt
docker run --rm --gpus all -e ACCEPT_EULA=Y \
  -v /home/ubuntu/kit:/kit \
  -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro \
  --entrypoint /isaac-sim/python.sh \
  nvcr.io/nvidia/isaac-sim:4.5.0 /kit/scripts/s4_bigscene.py 2>&1 | tee kit/out/s4_bigscene.log

python3 kit/extract_timings.py kit/out/s4_bigscene --warmup 20 --start-epoch kit/out/s4_bigscene_start.txt
```
(mtime timing is adequate here: multi-second frames, far above the 1s floor. Copy
`extract_timings.py` from the old kit into `kit/` if not already there:
it ships in `session_kit/`.) Record the JSON verbatim. The 2x-corridor judgment
happens at home, not on the meter.

## 7. D3 - raster with sub-second timing (300 frames, ~1 min render)
```bash
docker run --rm --gpus all -e ACCEPT_EULA=Y \
  -v /home/ubuntu/kit:/kit \
  -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro \
  --entrypoint /isaac-sim/python.sh \
  nvcr.io/nvidia/isaac-sim:4.5.0 /kit/scripts/s4_raster_timed.py 2>&1 | tee kit/out/s4_raster.log

python3 kit/extract_sidecar_timings.py kit/out/s4_raster_times.json --warmup 100
```
First look: `distinct_delta_values`. >> 2 -> the watcher resolved the signal, the
CV is now meaningful either way. Record the JSON verbatim.

## 8. Download everything, THEN terminate
```bash
# from the Mac:
scp -i ~/Downloads/calibration.pem -r ubuntu@<IP>:/home/ubuntu/kit/out ~/Desktop/finops-governor/kit/out_s4
```
Verify locally (`ls`, spot-open frames) BEFORE terminating. Nothing on that box
survives termination.

## 9. Teardown
EC2 console -> terminate `finops-s4`. Confirm state = terminated. Stop the timer;
record wall-clock and billed hours.

## 10. Post-session (Mac, meter off)
1. **Video assembly** (D1):
```bash
cd ~/Desktop/finops-governor/kit/out_s4/s4_demo
ffmpeg -framerate 8 -pattern_type glob -i '**/rgb_*.png' -c:v libx264 -pix_fmt yuv420p ../s4_frames.mp4
# then concatenate: terminal segment (phase 0) + s4_frames.mp4 -> demo video
# simplest: iMovie/QuickTime drag-and-drop, or ffmpeg concat demuxer
```
2. **D2 judgment**: measured mean vs 3.5897 prediction; inside [1.79, 7.18] -> model
   holds outside its calibration point, one sentence in cost-model.md; outside ->
   documented model limit (scene-complexity term named as the missing variable).
3. **D3 judgment**: rasterize_factor = measured_raster_s / measured_ref_s (use the
   D2-run reference only if re-measured; else the session-3 3.5897). CV < 0.20 ->
   new measured factor lands in hardware_profiles.json (fail-safe rounding, upward);
   CV >= 0.20 -> 0.03 stays, now backed by a real sub-second measurement.
4. **Docs**: ADR 0009 amendment update (D3 closes the open item with data), ADR 0011
   if D2 breaks the corridor, calibration.md session-4 section, ROADMAP (demo video
   Remaining item -> Done), demo/ gets the new video, provenance.txt digest-pinned.
5. Hand the three JSONs + logs to Claude for the doc updates.

## Known failure modes (from sessions 1-3)
- NVIDIA GPU-Optimized AMI / driver 595.xx -> container segfaults. Use the pinned AMI.
- Missing `nvoptix.bin` mount -> OptiX denoiser failure.
- Files existing != scene rendering. Checkpoint 2.5 is mandatory.
- Long heredocs into the terminal jam - every command above is single-line-safe.
