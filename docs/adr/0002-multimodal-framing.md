# ADR 0002 — Scope to multimodal / digital-twin data, not tabular

**Status:** Accepted

## Context

A governor pattern (NL → plan → cost → gate → execute) is modality-agnostic. But
its two gate checks only carry weight for certain data types.

## Decision

Scope the project to multimodal digital-twin generation (rendered images + depth,
segmentation, poses) via OpenUSD / Omniverse Replicator / Isaac Sim.

## Consequences

- The FinOps premise holds: visual/3D generation is GPU-bound and genuinely
  expensive. (Tabular synthetic data is near-free, which would void the thesis.)
- The geometric-validity check is meaningful: "clipping through the floor" only
  exists for 3D scenes.
- OpenUSD and Isaac/Replicator skills become load-bearing, not decorative.
- The validity gate runs on the **scene description**, never on rendered pixels,
  preserving "block before spend."