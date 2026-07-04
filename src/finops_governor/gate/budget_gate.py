"""Budget gate (M2, Task 2.5).

The deterministic gate's approve / block paths. Given a plan, it estimates the cost via
an injected CostModel and compares it to the plan's budget:

    cost <= budget  ->  APPROVE
    cost >  budget  ->  BLOCK   (Task 2.6 will attempt a MODIFY here before blocking)

The gate depends only on the CostModel *interface*, never on a concrete implementation.
That single indirection is what makes the governor substrate-agnostic: swap in a CPU or
TPU cost model and the gate is unchanged. The comparison is exact and reproducible: same
plan + same cost model -> same verdict, every time.
"""

from finops_governor.estimator.base import CostModel
from finops_governor.gate.decision import GateDecision
from finops_governor.schemas import GenerationPlan


class BudgetGate:
    """Approve a plan if its estimated cost is within budget, else block it."""

    def __init__(self, cost_model: CostModel) -> None:
        self._cost_model = cost_model

    def evaluate(self, plan: GenerationPlan) -> GateDecision:
        estimate = self._cost_model.estimate(plan)
        budget = plan.budget.max_usd

        if estimate.total_usd <= budget:
            return GateDecision.approve(plan.plan_id, estimate, budget)

        # Over budget. Task 2.6 will attempt a modification here before blocking;
        # until then, an over-budget plan is blocked outright.
        return GateDecision.block(plan.plan_id, estimate, budget)
