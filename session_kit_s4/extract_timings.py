#!/usr/bin/env python3
"""Extract per-frame render timings from BasicWriter output (M9, calibration).

Measurement from artifacts: BasicWriter writes one rgb_*.png per frame; consecutive
file mtimes give per-frame wall-clock deltas. Per docs/calibration.md section 3: the
first WARMUP frames are discarded (shader/JIT compilation), and the steady state is
reported as mean / std / CV against the acceptance criterion (CV < 0.20).

Usage:
    python3 extract_timings.py out/r1_ref [--warmup 20] [--start-epoch out/r1_start.txt]

--start-epoch (a file containing `date +%s` taken just before launch) additionally
reports ingestion time: start -> first frame.
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
    ap.add_argument("output_dir")
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--start-epoch", default=None)
    args = ap.parse_args()

    frames = sorted(
        (int(m.group(1)), p)
        for p in Path(args.output_dir).rglob("*.png")
        if (m := _FRAME.search(p.name))
    )
    if len(frames) < args.warmup + 10:
        print(f"error: only {len(frames)} frames; need warmup+10", file=sys.stderr)
        return 1

    mtimes = [p.stat().st_mtime for _, p in frames]
    deltas = [b - a for a, b in zip(mtimes, mtimes[1:])]
    steady = deltas[args.warmup :]
    mean = statistics.mean(steady)
    std = statistics.stdev(steady)
    cv = std / mean if mean else float("inf")

    result = {
        "output_dir": args.output_dir,
        "frames": len(frames),
        "warmup_discarded": args.warmup,
        "steady_frames": len(steady),
        "mean_s_per_frame": round(mean, 4),
        "std_s": round(std, 4),
        "cv": round(cv, 4),
        "cv_acceptable": cv < 0.20,
    }
    if args.start_epoch:
        start = float(Path(args.start_epoch).read_text().strip())
        result["ingestion_s"] = round(mtimes[0] - start, 2)

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
