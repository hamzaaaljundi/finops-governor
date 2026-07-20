#!/usr/bin/env python3
"""Coverage analysis (M9, Task 9.5): does the coupon-collector prediction hold?

Measures the number of VISUALLY DISTINCT frames in a rendered set and compares it
against the diversity model's expected-coverage prediction E[distinct] =
k*(1-(1-1/k)^n) (docs/diversity-model.md). Run against the M9.2 coverage pair:

    python3 coverage_analysis.py kit/out/cov_redundant kit/out/cov_trimmed \
        --capacity 16 --out coverage_results.json

Method: each frame is embedded as a downsampled 32x32 RGB pixel vector. Pixel space
is chosen DELIBERATELY over semantic embeddings (CLIP et al.): the experiment's
configurations differ by object rotation and lighting intensity, axes semantic
models are partially invariant to; pixel space preserves both. Distinctness is
leader-clustering under a threshold auto-derived from the pairwise-distance
distribution (Otsu), reported in the output for auditability (--threshold overrides).

Requires: pillow, numpy.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def embed_dir(d: Path, size: int = 32) -> tuple[np.ndarray, int]:
    files = sorted(d.rglob("rgb_*.png"))
    if not files:
        raise SystemExit(f"error: no rgb_*.png under {d}")
    vecs = []
    for f in files:
        img = Image.open(f).convert("RGB").resize((size, size), Image.BILINEAR)
        vecs.append(np.asarray(img, dtype=np.float64).ravel() / 255.0)
    return np.stack(vecs), len(files)


def pairwise_distances(x: np.ndarray) -> np.ndarray:
    sq = (x * x).sum(axis=1)
    d2 = sq[:, None] + sq[None, :] - 2.0 * (x @ x.T)
    np.maximum(d2, 0.0, out=d2)
    d = np.sqrt(d2)
    return d[np.triu_indices(len(x), k=1)]


def otsu_threshold(values: np.ndarray, bins: int = 256) -> float:
    spread = float(values.max() - values.min()) if values.size else 0.0
    if values.size == 0 or spread < 1e-9:
        # Degenerate: all pairwise distances (near-)identical. Any threshold above
        # the common value yields one cluster; report that honestly.
        return float(values.max() + 1e-6) if values.size else 1e-6
    hist, edges = np.histogram(values, bins=bins)
    hist = hist.astype(np.float64)
    total = hist.sum()
    centers = (edges[:-1] + edges[1:]) / 2.0
    best_t, best_var = float(values.mean()), -1.0
    w0 = np.cumsum(hist)
    w1 = total - w0
    mu_cum = np.cumsum(hist * centers)
    mu_total = mu_cum[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        mu0 = mu_cum / w0
        mu1 = (mu_total - mu_cum) / w1
        between = w0 * w1 * (mu0 - mu1) ** 2
    if not np.isfinite(between).any():
        return float(np.median(values))
    idx = int(np.nanargmax(between))
    if between[idx] > best_var:
        best_t = float(centers[idx])
    return best_t


def leader_cluster(x: np.ndarray, threshold: float) -> list[int]:
    leaders: list[np.ndarray] = []
    sizes: list[int] = []
    for v in x:
        for i, ld in enumerate(leaders):
            if np.linalg.norm(v - ld) < threshold:
                sizes[i] += 1
                break
        else:
            leaders.append(v)
            sizes.append(1)
    return sizes


def expected_distinct(n: int, k: int) -> float:
    return k * (1.0 - (1.0 - 1.0 / k) ** n)


def analyze(d: Path, capacity: int, threshold: float | None) -> dict:
    x, n = embed_dir(d)
    dists = pairwise_distances(x)
    t = threshold if threshold is not None else otsu_threshold(dists)
    sizes = sorted(leader_cluster(x, t), reverse=True)
    measured = len(sizes)
    predicted = expected_distinct(n, capacity)
    return {
        "dir": str(d),
        "frames": n,
        "threshold": round(t, 4),
        "threshold_source": "manual" if threshold is not None else "otsu(pairwise)",
        "distance_stats": {
            "min": round(float(dists.min()), 4),
            "median": round(float(np.median(dists)), 4),
            "max": round(float(dists.max()), 4),
        },
        "measured_distinct": measured,
        "predicted_distinct": round(predicted, 2),
        "cluster_sizes": sizes[:20],
        "measured_redundant_fraction": round(1.0 - measured / n, 4),
        "predicted_redundant_fraction": round(1.0 - predicted / n, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--capacity", type=int, required=True, help="declared capacity k")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    results = [analyze(Path(d), args.capacity, args.threshold) for d in args.dirs]
    report = {"capacity_k": args.capacity, "results": results}
    print(json.dumps(report, indent=2))
    for r in results:
        ok = abs(r["measured_distinct"] - r["predicted_distinct"]) <= max(
            2.0, 0.2 * r["predicted_distinct"]
        )
        print(
            f"# {Path(r['dir']).name}: measured {r['measured_distinct']} distinct "
            f"vs predicted {r['predicted_distinct']} -> "
            f"{'PREDICTION HOLDS' if ok else 'DEVIATION (document it)'}",
            file=sys.stderr,
        )
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
