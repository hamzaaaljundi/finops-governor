#!/usr/bin/env python3
"""Extract per-frame render timings from the s4 watcher sidecar (session 4, D3).

The sidecar (written by the in-script watcher thread) maps frame filename ->
time.monotonic() at first appearance, polled at 5ms - the sub-second timing source
ADR 0009's amendment requires for rasterize_factor. Output shape matches
session_kit/extract_timings.py so results are directly comparable, plus a
`distinct_delta_values` field: the diagnostic that exposed the mtime quantization
(2 distinct values = quantized; a healthy sub-second signal shows many).

Usage:
    python3 extract_sidecar_timings.py out/s4_raster_times.json [--warmup 100]
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

_FRAME = re.compile(r"rgb_(\d+)\.png$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sidecar")
    ap.add_argument("--warmup", type=int, default=100)
    args = ap.parse_args()

    raw = json.loads(Path(args.sidecar).read_text())
    frames = sorted((int(m.group(1)), t) for name, t in raw.items() if (m := _FRAME.search(name)))
    if len(frames) < args.warmup + 10:
        print(f"error: only {len(frames)} frames; need warmup+10", file=sys.stderr)
        return 1

    times = [t for _, t in frames]
    deltas = [b - a for a, b in zip(times, times[1:])]
    steady = deltas[args.warmup :]
    mean = statistics.mean(steady)
    std = statistics.stdev(steady)
    cv = std / mean if mean else float("inf")

    result = {
        "sidecar": args.sidecar,
        "frames": len(frames),
        "warmup_discarded": args.warmup,
        "steady_frames": len(steady),
        "mean_s_per_frame": round(mean, 4),
        "std_s": round(std, 4),
        "cv": round(cv, 4),
        "cv_acceptable": cv < 0.20,
        "distinct_delta_values": len({round(d, 3) for d in steady}),
        "min_delta_s": round(min(steady), 4),
        "max_delta_s": round(max(steady), 4),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
