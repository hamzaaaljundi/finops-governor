# ADR 0004 - Freeze the CheckContext now; defer lazy USD stage loading to M5

**Status:** Accepted

## Context

Validity checks (cost, and later diversity and USD geometry) each receive a shared
`CheckContext`. Two properties were considered up front:

1. **Immutability.** If one check could mutate the context or the plan, another check's
   result would depend on run order - destroying the determinism the whole governor
   relies on.
2. **Lazy loading.** A future USD check (M5) may need a loaded OpenUSD stage, which can be
   multi-gigabyte. Eagerly loading it into every context would be an expensive waste when
   most checks never touch it.

## Decision

- **Freeze the context now.** `CheckContext`, `Finding`, and `ValidityReport` are frozen
  Pydantic models (`frozen=True`); findings are held as an immutable tuple. Checks receive
  read-only inputs and are contractually pure reads. Mutation raises at runtime.
- **Defer lazy USD loading to M5.** The context is deliberately minimal now (`plan` +
  `cost_estimate`). The lazy-stage field is NOT added yet, because:
  - No check currently needs a stage; code no current test can exercise is speculative.
  - The right loading shape can only be chosen against the real `usd-core` API (USD is
    itself lazy internally via payloads/layers - we may not need our own machinery).
  - The context is a Pydantic model, so adding an optional field in M5 is a backward-
    compatible one-line change - the same additive pattern used for the M1 randomization
    block.

## Consequences

- Determinism is enforced at the boundary: a check cannot swap out or replace what it was
  given, nor mutate shared findings.
- Deep immutability of the plan's internals is not enforced by freezing the plan models
  (that would touch the tagged M1 schema); it rests on the "checks are pure reads"
  contract. Deep-freezing plan models remains an available future hardening.
- M5 adds lazy stage access to `CheckContext` when the USD check is built, guided by the
  real library rather than a guess made now.
