"""Budget gate (M2, Tasks 2.5 + 2.6).

.. deprecated:: M3
    Superseded by the multi-axis ``Governor`` (``finops_governor.governor``), which is a
    proven strict superset: ``Governor.with_cost_check(model)`` reproduces this gate's
    behavior exactly (see tests/test_governor.py parity tests). BudgetGate is retained
    for the M2 release history and parity tests only; new code should use the Governor.

The deterministic gate. Given a plan, it estimates the cost via an injected CostModel
and compares it to the plan's budget:

    cost <= budget                      ->  APPROVE
    cost >  budget, modifier recovers   ->  MODIFY   (a cheaper, budget-fitting variant)
    cost >  budget, unrecoverable       ->  BLOCK

The gate depends only on the CostModel *interface* (and, optionally, a PlanModifier),
never on a concrete cost implementation - which is what keeps the governor
substrate-agnostic. Same plan + same model + same modifier -> same verdict, every time.

Without a modifier the gate is a pure approve/block gate (Task 2.5 behavior).
"""

from finops_governor.estimator.base import CostModel
from finops_governor.gate.decision import GateDecision
from finops_governor.gate.modifier import PlanModifier
from finops_governor.schemas import GenerationPlan


class BudgetGate:
    """Approve, modify, or block a plan based on its estimated cost vs. budget.

    Deprecated since M3: use ``Governor.with_cost_check`` (or ``with_default_checks``).
    """

    def __init__(self, cost_model: CostModel, modifier: PlanModifier | None = None) -> None:
        self._cost_model = cost_model
        self._modifier = modifier

    def evaluate(self, plan: GenerationPlan) -> GateDecision:
        estimate = self._cost_model.estimate(plan)
        budget = plan.budget.max_usd

        if estimate.total_usd <= budget:
            return GateDecision.approve(plan.plan_id, estimate, budget)

        # Over budget: try to recover with a cheaper variant before blocking.
        if self._modifier is not None:
            proposal = self._modifier.propose(plan, budget)
            if proposal is not None:
                return GateDecision.modify(
                    plan.plan_id,
                    estimate,
                    budget,
                    proposal.plan,
                    proposal.estimate,
                    proposal.modifications,
                )

        return GateDecision.block(plan.plan_id, estimate, budget)
