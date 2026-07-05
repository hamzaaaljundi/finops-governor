# ADR 0005 - Composition precedence for the multi-axis gate

**Status:** Accepted

## Context

The Governor runs several validity checks (cost now; diversity M4; USD geometry M5) and
must combine their findings into one verdict. With more than one axis, findings can
conflict - e.g. the cost axis says a job is over-budget-but-recoverable (MODIFIABLE)
while a geometry axis says the scene is invalid (BLOCKING). A single, documented rule is
needed so the outcome is deterministic and defensible.

## Decision

Resolve the verdict from the aggregated report by severity precedence, highest first:

1. **Any BLOCKING finding -> BLOCK.** The job is invalid or unsafe; do not run it and do
   not attempt to modify it.
2. **Any MODIFIABLE finding -> MODIFY.** The job is recoverable; propose a fitting variant.
3. **Otherwise -> APPROVE.** Clean, or warnings only.

Rules:
- **BLOCKING dominates MODIFIABLE.** There is no point proposing a cheaper variant of a
  fundamentally invalid job.
- **WARNING never changes the verdict.** It is advisory.
- **Every finding is recorded** in the decision's reason for audit, not just the deciding
  one - a BLOCK caused by geometry still reports the co-occurring cost finding.
- **Only the cost axis can produce a MODIFY** (decision 2). Other axes are block-or-warn.
  The modify proposal is built by the PlanModifier.

The policy is a pure function (`validity.composition.resolve_verdict`), tested
exhaustively over severity combinations independently of the checks that produce them.

## Consequences

- The verdict is deterministic and order-independent: it depends only on the multiset of
  severities present, not on which check ran first.
- New axes slot in without touching the policy - they only decide which severity to emit.
- Extending MODIFY to non-cost axes later would require composing multiple proposals; that
  is deliberately out of scope now and would be a new decision.
