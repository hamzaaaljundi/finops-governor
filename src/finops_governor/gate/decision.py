"""Gate decision types (M2, Task 2.4).

The gate's OUTPUT contract — the mirror of GenerationPlan (the input). A GateDecision
records one of three verdicts (approve / modify / block) together with the reasoning and
the cost basis that produced it, so every decision is auditable (M5) and the orchestrator
(M5) has a single object to branch on.

The model is self-validating: its invariants make an inconsistent decision impossible to
construct — e.g. an APPROVE whose cost exceeds budget, or a MODIFY with no modified plan.
Use the approve / block / modify factories to build decisions at the gate's call sites.
"""

from enum import Enum

from pydantic import Field, model_validator

from finops_governor.estimator.estimate import CostEstimate
from finops_governor.schemas import GenerationPlan
from finops_governor.schemas.models import StrictModel


class Verdict(str, Enum):
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    BLOCK = "BLOCK"


class GateDecision(StrictModel):
    """The result of running a plan through the gate.

    modified_plan / modified_estimate / modifications are populated only for MODIFY.
    """

    verdict: Verdict
    plan_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    estimate: CostEstimate  # cost basis of the original plan
    budget_usd: float = Field(..., gt=0)

    modified_plan: GenerationPlan | None = None
    modified_estimate: CostEstimate | None = None
    modifications: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> "GateDecision":
        carries_mod = (
            self.modified_plan is not None
            or self.modified_estimate is not None
            or bool(self.modifications)
        )

        if self.verdict is Verdict.APPROVE:
            if carries_mod:
                raise ValueError("APPROVE must not carry a modification.")
            if self.estimate.total_usd > self.budget_usd:
                raise ValueError(
                    "APPROVE requires the estimated cost to be within budget."
                )
        elif self.verdict is Verdict.BLOCK:
            if carries_mod:
                raise ValueError("BLOCK must not carry a modification.")
        else:  # MODIFY
            if self.modified_plan is None or self.modified_estimate is None:
                raise ValueError("MODIFY requires a modified plan and its estimate.")
            if not self.modifications:
                raise ValueError("MODIFY requires a description of the changes.")
            if self.modified_estimate.total_usd > self.budget_usd:
                raise ValueError(
                    "MODIFY requires the modified estimate to be within budget."
                )
        return self

    # --- factories: readable, guaranteed-valid construction at the gate ---

    @classmethod
    def approve(
        cls,
        plan_id: str,
        estimate: CostEstimate,
        budget_usd: float,
        reason: str | None = None,
    ) -> "GateDecision":
        reason = reason or (
            f"Estimated ${estimate.total_usd:.2f} is within the "
            f"${budget_usd:.2f} budget."
        )
        return cls(
            verdict=Verdict.APPROVE,
            plan_id=plan_id,
            reason=reason,
            estimate=estimate,
            budget_usd=budget_usd,
        )

    @classmethod
    def block(
        cls,
        plan_id: str,
        estimate: CostEstimate,
        budget_usd: float,
        reason: str | None = None,
    ) -> "GateDecision":
        reason = reason or (
            f"Estimated ${estimate.total_usd:.2f} exceeds the ${budget_usd:.2f} "
            "budget and cannot be brought within it by modification."
        )
        return cls(
            verdict=Verdict.BLOCK,
            plan_id=plan_id,
            reason=reason,
            estimate=estimate,
            budget_usd=budget_usd,
        )

    @classmethod
    def modify(
        cls,
        plan_id: str,
        estimate: CostEstimate,
        budget_usd: float,
        modified_plan: GenerationPlan,
        modified_estimate: CostEstimate,
        modifications: list[str],
        reason: str | None = None,
    ) -> "GateDecision":
        reason = reason or (
            f"Original estimate ${estimate.total_usd:.2f} exceeded the "
            f"${budget_usd:.2f} budget; modified plan estimated at "
            f"${modified_estimate.total_usd:.2f}."
        )
        return cls(
            verdict=Verdict.MODIFY,
            plan_id=plan_id,
            reason=reason,
            estimate=estimate,
            budget_usd=budget_usd,
            modified_plan=modified_plan,
            modified_estimate=modified_estimate,
            modifications=modifications,
        )
