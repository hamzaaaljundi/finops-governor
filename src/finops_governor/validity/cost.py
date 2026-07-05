"""Cost/budget validity check (M3, Task 3.2).

Ports M2's budget logic behind the ValidityCheck interface - it wraps the existing
estimator (via the pre-computed estimate in the context) and PlanModifier; it does not
reimplement them.

Emits:
  * within budget                    -> no findings (clean)
  * over budget, recoverable         -> one MODIFIABLE finding
  * over budget, not recoverable     -> one BLOCKING finding

Recoverability has a single source of truth: the PlanModifier. If the modifier can fit
the plan, it is MODIFIABLE; if it returns None, it is BLOCKING. This guarantees the check
never reports a plan as modifiable that the modifier cannot actually fix.
"""

from finops_governor.gate.modifier import PlanModifier
from finops_governor.validity.models import CheckContext, Finding, Severity


class CostCheck:
    name = "cost_budget"

    def __init__(self, modifier: PlanModifier) -> None:
        self._modifier = modifier

    def check(self, context: CheckContext) -> list[Finding]:
        budget = context.plan.budget.max_usd
        estimated = context.cost_estimate.total_usd

        if estimated <= budget:
            return []

        detail: dict[str, float | str] = {
            "estimated_usd": round(estimated, 4),
            "budget_usd": budget,
        }
        proposal = self._modifier.propose(context.plan, budget)

        if proposal is None:
            return [
                Finding(
                    check_name=self.name,
                    severity=Severity.BLOCKING,
                    reason=(
                        f"Estimated ${estimated:.2f} exceeds the ${budget:.2f} budget "
                        "and cannot be recovered by modification."
                    ),
                    detail=detail,
                )
            ]

        recovered = proposal.estimate.total_usd
        return [
            Finding(
                check_name=self.name,
                severity=Severity.MODIFIABLE,
                reason=(
                    f"Estimated ${estimated:.2f} exceeds the ${budget:.2f} budget; "
                    f"recoverable by trimming variations to ~${recovered:.2f}."
                ),
                detail={**detail, "recovered_usd": round(recovered, 4)},
            )
        ]
