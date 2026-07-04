"""Plan modifier (M2, Task 2.6).

When a plan is over budget, propose a cheaper variant that fits - rather than blocking
outright. Strategy: proportionally reduce the number of variations per scene, preserving
per-image fidelity (resolution, samples, modalities). This trims *how many* samples, not
their quality - and where a scene declares randomization, trimming variations moves the
job toward the point of diminishing training value (the diversity gate, M4, makes that
value explicit).

The search is black-box against the CostModel interface (binary search over a global
scale factor), so the modifier is substrate-agnostic like the gate - it never assumes
the GPU cost formula. Every candidate is re-validated through the GenerationPlan schema,
so a proposal is always itself a valid plan.

If even the minimum plan (one variation per scene) exceeds budget, the job is
unrecoverable and propose() returns None (the gate then blocks).
"""

from typing import NamedTuple

from finops_governor.estimator.base import CostModel
from finops_governor.estimator.estimate import CostEstimate
from finops_governor.schemas import GenerationPlan

_SEARCH_ITERATIONS = 40


class ModifyProposal(NamedTuple):
    plan: GenerationPlan
    estimate: CostEstimate
    modifications: list[str]


class PlanModifier:
    """Propose a budget-fitting variant by proportionally reducing variation counts."""

    def __init__(self, cost_model: CostModel) -> None:
        self._cost_model = cost_model

    def propose(self, plan: GenerationPlan, budget_usd: float) -> ModifyProposal | None:
        # Unrecoverable if even the minimum plan (1 variation/scene) is over budget.
        floor_plan = self._scaled(plan, 0.0)
        if self._cost_model.estimate(floor_plan).total_usd > budget_usd:
            return None

        # Largest global scale whose estimated cost fits the budget (binary search).
        lo, hi = 0.0, 1.0
        best = floor_plan
        for _ in range(_SEARCH_ITERATIONS):
            mid = (lo + hi) / 2
            candidate = self._scaled(plan, mid)
            if self._cost_model.estimate(candidate).total_usd <= budget_usd:
                best = candidate
                lo = mid
            else:
                hi = mid

        estimate = self._cost_model.estimate(best)
        return ModifyProposal(
            plan=best,
            estimate=estimate,
            modifications=self._describe(plan, best),
        )

    def _scaled(self, plan: GenerationPlan, scale: float) -> GenerationPlan:
        data = plan.model_dump()
        for scene in data["scenes"]:
            scene["variation_count"] = max(1, round(scene["variation_count"] * scale))
        # Re-validate: a modified plan must itself be a valid GenerationPlan.
        return GenerationPlan.model_validate(data)

    @staticmethod
    def _describe(original: GenerationPlan, modified: GenerationPlan) -> list[str]:
        changes: list[str] = []
        for o, m in zip(original.scenes, modified.scenes):
            if o.variation_count != m.variation_count:
                changes.append(
                    f"scene '{o.scene_id}': variation_count "
                    f"{o.variation_count} -> {m.variation_count}"
                )
        return changes
