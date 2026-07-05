# ADR 0006 - Lazy USD stage loading lives in the geometry check, not CheckContext

**Status:** Accepted (refines ADR 0004)

## Context

ADR 0004 froze the `CheckContext` at M3 and deferred lazy USD stage loading to M5,
anticipating that a lazy-stage field would be added to the context "guided by the real
usd-core API rather than a guess." The M5 spike met that API, which clarified the design.

## Decision

Lazy USD stage loading lives in a memoizing `UsdStageLoader` owned by the geometry check -
**not** as a field on the shared `CheckContext`.

Rationale, by the context's own design principle: `CheckContext` carries inputs used by
*multiple* checks (the plan; the cost estimate, read by both cost and diversity). A USD
stage is consumed by *only* the geometry axis. By the same single-consumer principle that
justifies what is in the context, the stage belongs to its one consumer.

This also:
- keeps `CheckContext` serializable (audit round-trip) - a `Usd.Stage` is not JSON-serializable;
- isolates the heavy `pxr` dependency to one module instead of the shared context;
- preserves laziness and adds memoization: a stage opens only when the geometry check runs,
  and each path opens at most once per loader.

## Consequences

- `CheckContext` is unchanged from M3 - still frozen, minimal, serializable.
- The geometry check (Task 5.4) constructs/holds a `UsdStageLoader` and resolves stage paths
  from the plan.
- `Usd.Stage.Open` raises `Tf.ErrorException` on unreadable/missing layers; the loader wraps
  this in `UsdStageError`, which the asset-existence check catches to emit a finding.
- If a future axis also needs stages, a shared loader can be introduced then; it is not built
  speculatively now.
