# Calibration Environment (M9.2 session record)

Constants are meaningless without their environment. The measured values in
`hardware_profiles.json` and `gpu.py` were produced under exactly:

| Component | Value |
|---|---|
| Cloud instance | AWS EC2 `g5.xlarge` (us-east-1) |
| GPU | NVIDIA A10G, 24 GB (GA102), ECC on |
| AMI | Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04) 20240915 |
| NVIDIA driver | 550.90.07 |
| CUDA | 12.4 |
| Kernel | 6.5.0-1024-aws |
| Container | `nvcr.io/nvidia/isaac-sim:4.5.0` (headless, `--entrypoint /isaac-sim/python.sh`) |
| Workload | adapter-generated Replicator scripts (`session_kit/scripts/`), patched with the SimulationApp bootstrap |
| Timing method | BasicWriter frame-file mtime deltas; first 20 frames discarded (50 for the 300-frame R5 rerun); mean/std/CV per `session_kit/extract_timings.py` |
| Raw artifacts | `docs/calibration/timings/*.json`, key logs in `docs/calibration/logs/` |

Notable environment findings: the 2026-era 595.xx driver line crashes both
`isaac-sim:4.2.0` and `:5.1.0` at RTX renderer startup (identical segfault in
`librtx.scenedb.plugin.so`) - the dated 2024 AMI with the factory-matched 550-series
driver was required. Shader caches must be volume-mounted across container runs or
every run pays ~15 minutes of recompilation (the cold/warm ingestion split in
cost-model.md section 5).
