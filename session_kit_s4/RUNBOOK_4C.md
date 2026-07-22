# Session 4c Mini-Runbook - execute the fixed kit (D1 video frames, D2 bigscene, D3 lit raster)

Everything hard was done in 4a (ADR 0011); this is pure execution. Hard cap **$10**;
expected ~1.5 h wall / ~$2. Same pinned AMI (Deep Learning Base OSS Nvidia Driver
GPU AMI (Ubuntu 22.04) 20240915), g5.xlarge, image pulled BY DIGEST. Everything runs
in tmux. Download after EACH deliverable (ADR 0011, decision 4).

## Pre-flight (Mac)
- [ ] `pytest tests/test_frozen_kits.py -q` passes (kit matches manifest)
- [ ] `grep -c Dome session_kit_s4/scripts/s4_demo_trimmed.py` prints >= 1
- [ ] Assets present: `ls session_kit_s4/assets/` shows the three .usda files

## 1-3. Launch / upload / pull (same as 4b, by digest)
```bash
scp -i ~/Downloads/calibration.pem -r ~/Desktop/finops-governor/session_kit_s4 ubuntu@IP:/home/ubuntu/kit
ssh -i ~/Downloads/calibration.pem ubuntu@IP
tmux new -s s4
mkdir -p /home/ubuntu/kit/out
docker login nvcr.io
docker pull nvcr.io/nvidia/isaac-sim@sha256:c2f47dc82a7714af08d3766efe80ac9d084c2b37b5d0dfbd074797ec56390fc7
```

## 4. Smoke (8 frames) + the FIXED gate - mandatory, no exceptions this time
```bash
cd /home/ubuntu
sed 's/num_frames=96/num_frames=8/' kit/scripts/s4_demo_trimmed.py > kit/scripts/smoke.py
docker run --rm --gpus all -e ACCEPT_EULA=Y -v /home/ubuntu/kit:/kit -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro --entrypoint /isaac-sim/python.sh nvcr.io/nvidia/isaac-sim@sha256:c2f47dc82a7714af08d3766efe80ac9d084c2b37b5d0dfbd074797ec56390fc7 /kit/scripts/smoke.py 2>&1 | tee kit/out/smoke.log
python3 -m pip install --user pillow numpy -q
python3 -c "import glob; from PIL import Image; import numpy as np; a = np.asarray(Image.open(sorted(glob.glob('kit/out/s4_demo/**/rgb_*.png', recursive=True))[0]).convert('RGB')); print('RGB-only mean:', round(float(a.mean()), 2))"
```
Expect RGB-only mean in the ~150-200 range (session-3 lit frames sit at ~185).
Near 0 = still black: STOP, scp a frame home, diagnose. 63.75 exactly = you forgot
.convert('RGB'). **Also scp one smoke frame home and LOOK at it before proceeding:**
```bash
# Mac: scp -i ~/Downloads/calibration.pem ubuntu@IP:/home/ubuntu/kit/out/s4_demo/rgb_0000.png ~/Desktop/smoke_4c.png && open ~/Desktop/smoke_4c.png
```
Then clear: `rm -rf kit/out/s4_demo`

## 5. D1 - demo frames (96), download IMMEDIATELY after
```bash
docker run --rm --gpus all -e ACCEPT_EULA=Y -v /home/ubuntu/kit:/kit -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro --entrypoint /isaac-sim/python.sh nvcr.io/nvidia/isaac-sim@sha256:c2f47dc82a7714af08d3766efe80ac9d084c2b37b5d0dfbd074797ec56390fc7 /kit/scripts/s4_demo_trimmed.py 2>&1 | tee kit/out/s4_demo.log
ls kit/out/s4_demo/rgb_*.png | wc -l   # 96
# pixel-check first AND last with .convert('RGB'), then from the Mac:
# scp -i ~/Downloads/calibration.pem -r ubuntu@IP:/home/ubuntu/kit/out/s4_demo ~/Desktop/finops-governor/kit/out_s4c_demo
```

## 6. D2 - bigscene (150), timing + download
```bash
date +%s > kit/out/s4_bigscene_start.txt
docker run --rm --gpus all -e ACCEPT_EULA=Y -v /home/ubuntu/kit:/kit -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro --entrypoint /isaac-sim/python.sh nvcr.io/nvidia/isaac-sim@sha256:c2f47dc82a7714af08d3766efe80ac9d084c2b37b5d0dfbd074797ec56390fc7 /kit/scripts/s4_bigscene.py 2>&1 | tee kit/out/s4_bigscene.log
python3 kit/extract_timings.py kit/out/s4_bigscene --warmup 20 --start-epoch kit/out/s4_bigscene_start.txt
```
Pixel-check (RGB-only!) before trusting the timing. 2x corridor vs 3.5897 judged at
home. Download the timing JSON + a sample frame; full frame download optional.

## 7. D3 - lit raster (300), timing + download
```bash
docker run --rm --gpus all -e ACCEPT_EULA=Y -v /home/ubuntu/kit:/kit -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro --entrypoint /isaac-sim/python.sh nvcr.io/nvidia/isaac-sim@sha256:c2f47dc82a7714af08d3766efe80ac9d084c2b37b5d0dfbd074797ec56390fc7 /kit/scripts/s4_raster_plain.py 2>&1 | tee kit/out/s4_raster.log
python3 kit/extract_timings.py kit/out/s4_raster --warmup 100
```
Pixel-check (RGB-only) - raster frames should also be lit. rasterize_factor =
raster mean / D2's SAME-DAY reference-scene rate if measured, else vs 3.5897;
judged at home with fail-safe rounding.

## 8. Final download of everything, verify locally, THEN terminate
```bash
# Mac:
scp -i ~/Downloads/calibration.pem -r ubuntu@IP:/home/ubuntu/kit/out ~/Desktop/finops-governor/kit/out_s4c
```
Terminate in console; confirm state = terminated; record wall/billed time.

## 9. Post-session (free)
1. Video: `ffmpeg -framerate 8 -pattern_type glob -i 'kit/out_s4c/s4_demo/rgb_*.png' -c:v libx264 -pix_fmt yuv420p kit/out_s4c/s4_frames.mp4`, concat with `session_kit_s4/s4_verdicts.mp4`, land in `demo/`.
2. Hand all JSONs + logs to Claude: D2 corridor judgment, D3 rasterize decision,
   calibration.md session-4 section, ADR amendments, ROADMAP + release notes.

## Known failure modes (cumulative, sessions 1-4a)
- Wrong AMI / driver 595.xx -> container segfaults. Use the pinned AMI.
- Missing nvoptix.bin mount -> denoiser errors (non-fatal but wrong regime).
- Object-first modify.attribute -> graph error, zero frames (ADR 0011).
- Sphere@1500 light or Euler-rotation camera -> SILENT black frames (ADR 0011).
- RGBA mean without .convert('RGB') -> 63.75 false-pass on black frames (ADR 0011).
- Watcher thread -> hung startup; use s4_raster_plain.py (mtimes resolved sub-second
  on this AMI anyway).
- Batch downloads at the end -> lost everything once. Download per deliverable.
- Files existing != frames rendered != frames LIT. Three different checks.
