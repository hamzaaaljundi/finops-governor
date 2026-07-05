# The Validity Gate - Design

> How the governor turns many independent checks into one decision. This is the code
> form of the project's headline: **budget-invalidity, geometric-invalidity, and low
> training-value are one class of problem - reasons not to spend GPU-hours on a job,
> catchable before you spend - and one gate composes them.**
>
> **Status:** Implemented (M3) - **Release:** `v0.3-validity-gate`

---

## 1. The idea

A generation job can be a bad idea for different reasons: it costs too much, its scene is
geometrically broken, or it would produce predictably redundant, low-value data. Rather
than a separate tool per concern, the governor treats each as a **validity axis** and runs
them all through one gate that emits a single approve / modify / block decision.

New axes are added by writing a check, not by changing the gate. Cost exists today
(M3); diversity (M4) and USD geometry (M5) plug into the same seam unchanged.

```
                 plan
                  |
      cost estimate (deterministic)
                  |
        +---------+---------+
        |     CheckContext  |   (frozen: plan + cost_estimate)
        +---------+---------+
                  |  handed read-only to each check
   +--------------+--------------+-------------------+
   |              |              |                   |
CostCheck   DiversityCheck   UsdGeometryCheck    ... (any ValidityCheck)
   |              |              |                   |
   +------ findings (severity + reason + detail) ----+
                  |
            ValidityReport
                  |
         composition precedence
                  |
     approve  /  modify  /  block   (one GateDecision)
```

## 2. The contract

**`ValidityCheck`** (interface) - anything that examines a plan and returns findings:

```
name: str
check(context: CheckContext) -> list[Finding]
```

The gate depends only on this interface, never on a concrete check.

**`CheckContext`** (frozen) - the read-only inputs every check receives: the `plan` and its
already-computed `cost_estimate`. Frozen so a check cannot mutate what it - or another
check - was given; this is what keeps the verdict independent of check order (ADR 0004).
Checks must be pure reads.

**`Finding`** (frozen) - one actionable, auditable problem: `check_name`, `severity`,
`reason`, and optional `detail`. Never a bare boolean.

**`Severity`**:

| Severity | Meaning | Effect on verdict |
|---|---|---|
| `BLOCKING` | invalid/unsafe; do not run | forces BLOCK |
| `MODIFIABLE` | over threshold but recoverable | yields MODIFY (cost axis only) |
| `WARNING` | advisory | recorded, never decisive |

**`ValidityReport`** - the aggregated findings, with read-only query helpers
(`is_clean`, `has_blocking`, `has_modifiable`, `warnings`).

## 3. Composition precedence (ADR 0005)

The report becomes a verdict by a single documented rule, highest precedence first:

1. any `BLOCKING` finding -> **BLOCK**
2. else any `MODIFIABLE` finding -> **MODIFY**
3. otherwise -> **APPROVE** (clean, or warnings only)

`BLOCKING` dominates `MODIFIABLE` deliberately: there is no point proposing a cheaper
variant of a fundamentally invalid job. The rule is a pure function
(`validity.composition.resolve_verdict`), so it is order-independent and exhaustively
tested. Every finding - not just the deciding one - is recorded in the decision's reason
for audit.

Only the cost axis can produce a MODIFY today; other axes are block-or-warn. The modify
proposal is built by the `PlanModifier`.

## 4. The Governor

`Governor` holds a cost model, a list of checks, and a modifier. `evaluate(plan)`
estimates cost, builds the frozen context, runs every check, aggregates findings, resolves
the verdict, and builds the `GateDecision`. With a single `CostCheck` registered it
reproduces the M2 `BudgetGate` exactly - the composed gate is a strict superset of the
budget gate.

```python
from finops_governor.governor import Governor
from finops_governor.estimator import GpuRenderCostModel, get_profile

governor = Governor.with_cost_check(GpuRenderCostModel(get_profile("a10g")))
decision = governor.evaluate(plan)   # -> GateDecision (approve / modify / block)
```

## 5. Adding a new axis

1. Write a class with `name: str` and `check(context) -> list[Finding]`.
2. Decide which `Severity` it emits and what `detail` it records.
3. Register it in the `Governor`'s check list.

No change to the gate, the composition policy, or the decision contract. The diversity
gate (M4) and USD geometry gate (M5) are exactly this.

## 6. Scope

- Checks are pre-execution and deterministic - they reason over the plan (and, later, the
  declared randomization and the USD stage), never over generated data.
- Only the cost axis modifies; extending MODIFY to other axes is a future decision.
- Deep immutability of the plan's internals rests on the "checks are pure reads" contract
  plus the frozen context (ADR 0004).
