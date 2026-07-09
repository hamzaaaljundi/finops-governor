"""The Governor - the composed multi-axis gate (M3-M5; value-aware modification in
M6.5, ADR 0007).

Runs every registered validity check over a plan, aggregates their findings into one
ValidityReport, and composes that into a single approve / modify / block decision.

Factory wiring:
  * with_cost_check     - budget axis only (M2 parity)
  * with_default_checks - plan-level axes: cost + diversity (no filesystem dependency)
  * with_all_checks     - cost + diversity + USD geometry (explicit opt-in; stage paths
                          must resolve on disk)

The MODIFY proposal is built in two ordered passes (ADR 0007): a VALUE pass first -
every scene with a diversity MODIFIABLE finding is trimmed to its justified variation
count (removing only expected-redundant frames, free in training-signal terms) - then a
BUDGET pass only if the value-trimmed plan still exceeds the budget (cutting real
signal, because now there is no alternative). Never cut signal while waste remains.

Precedence is unchanged (ADR 0005): BLOCKING dominates; warnings never decide.
"""

from finops_governor.estimator.base import CostModel
from finops_governor.gate.decision import GateDecision, Verdict
from finops_governor.gate.modifier import PlanModifier
from finops_governor.schemas import GenerationPlan
from finops_governor.validity.base import ValidityCheck
from finops_governor.validity.composition import resolve_verdict, summarize_findings
from finops_governor.validity.cost import CostCheck
from finops_governor.validity.diversity import DiversityCheck
from finops_governor.validity.models import (
    CheckContext,
    Finding,
    Severity,
    ValidityReport,
)


class Governor:
    """Compose validity checks into a single gate decision."""

    def __init__(
        self,
        cost_model: CostModel,
        checks: list[ValidityCheck],
        modifier: PlanModifier,
    ) -> None:
        self._cost_model = cost_model
        self._checks = list(checks)
        self._modifier = modifier

    @classmethod
    def with_cost_check(cls, cost_model: CostModel) -> "Governor":
        """Default wiring: a governor with only the budget axis (M2-equivalent)."""
        modifier = PlanModifier(cost_model)
        return cls(cost_model, [CostCheck(modifier)], modifier)

    @classmethod
    def with_default_checks(cls, cost_model: CostModel) -> "Governor":
        """Plan-level multi-axis wiring: budget + diversity/redundancy."""
        modifier = PlanModifier(cost_model)
        return cls(cost_model, [CostCheck(modifier), DiversityCheck()], modifier)

    @classmethod
    def with_all_checks(cls, cost_model: CostModel) -> "Governor":
        """All three axes: budget + diversity + USD geometry.

        Requires each scene's stage path to resolve on disk (M5 convention:
        Scene.environment.usd_path is the composed stage). Explicit opt-in because
        plans with placeholder paths would be blocked by the existence check.
        """
        # Deferred import: only pay for pxr/usd-core when geometry is requested.
        from finops_governor.validity.usd_geometry import UsdGeometryCheck

        modifier = PlanModifier(cost_model)
        return cls(
            cost_model,
            [CostCheck(modifier), DiversityCheck(), UsdGeometryCheck()],
            modifier,
        )

    def evaluate(self, plan: GenerationPlan) -> GateDecision:
        estimate = self._cost_model.estimate(plan)
        context = CheckContext(plan=plan, cost_estimate=estimate)

        findings: list[Finding] = []
        for check in self._checks:
            findings.extend(check.check(context))
        report = ValidityReport(findings=tuple(findings))

        verdict = resolve_verdict(report)
        budget = plan.budget.max_usd

        if verdict is Verdict.BLOCK:
            return GateDecision.block(
                plan.plan_id, estimate, budget, reason=summarize_findings(report)
            )

        if verdict is Verdict.MODIFY:
            proposal_plan, proposal_estimate, modifications = self._build_proposal(
                plan, estimate, budget, report
            )
            return GateDecision.modify(
                plan.plan_id,
                estimate,
                budget,
                proposal_plan,
                proposal_estimate,
                modifications,
                reason=summarize_findings(report),
            )

        # APPROVE: clean uses the default reason; warnings are recorded for audit.
        if report.findings:
            return GateDecision.approve(
                plan.plan_id, estimate, budget, reason=summarize_findings(report)
            )
        return GateDecision.approve(plan.plan_id, estimate, budget)

    # ------------------------------------------------------------------ #
    # The two-pass MODIFY proposal (ADR 0007)
    # ------------------------------------------------------------------ #

    def _build_proposal(
        self,
        plan: GenerationPlan,
        estimate,
        budget: float,
        report: ValidityReport,
    ):
        # Pass 1 - VALUE: trim flagged scenes to their justified counts.
        candidate, value_mods = self._value_trim(plan, report)
        candidate_estimate = (
            self._cost_model.estimate(candidate) if value_mods else estimate
        )

        # Pass 2 - BUDGET: only if the value-trimmed plan still exceeds the budget.
        if candidate_estimate.total_usd <= budget:
            return candidate, candidate_estimate, value_mods

        # A cost MODIFIABLE finding guarantees recoverability of the original plan;
        # the value-trimmed candidate is no more expensive, so it stays recoverable.
        proposal = self._modifier.propose(candidate, budget)
        budget_mods = [f"budget: {m}" for m in proposal.modifications]
        return proposal.plan, proposal.estimate, value_mods + budget_mods

    @staticmethod
    def _value_trim(
        plan: GenerationPlan, report: ValidityReport
    ) -> tuple[GenerationPlan, list[str]]:
        """Trim each diversity-flagged scene to its justified variation count.

        The target is read from the finding's detail - the check that fired declares
        the compliant count, keeping all coverage math in the diversity module.
        """
        targets: dict[str, int] = {}
        for f in report.findings:
            if (
                f.check_name == "diversity"
                and f.severity is Severity.MODIFIABLE
                and f.detail is not None
            ):
                targets[str(f.detail["scene_id"])] = int(
                    f.detail["justified_variation_count"]
                )
        if not targets:
            return plan, []

        data = plan.model_dump()
        mods: list[str] = []
        for scene in data["scenes"]:
            target = targets.get(scene["scene_id"])
            if target is not None and target < scene["variation_count"]:
                mods.append(
                    f"value: scene '{scene['scene_id']}': variation_count "
                    f"{scene['variation_count']} -> {target} (expected-coverage trim)"
                )
                scene["variation_count"] = target
        # Re-validate: a modified plan must itself be a valid GenerationPlan.
        return GenerationPlan.model_validate(data), mods
