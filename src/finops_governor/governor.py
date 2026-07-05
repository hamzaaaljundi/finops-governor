"""The Governor - the composed multi-axis gate (M3, Tasks 3.3 + 3.4).

Runs every registered validity check over a plan, aggregates their findings into one
ValidityReport, and composes that into a single approve / modify / block decision.

Depends only on the ValidityCheck interface, so new axes (diversity M4, USD geometry M5)
register without changing this class. With a single CostCheck registered, it reproduces
the M2 BudgetGate behavior exactly.

The composition policy (precedence + audit summary) lives in validity.composition and is
tested independently. Only the cost axis can produce a MODIFY (decision 2), so the modify
proposal is built by the PlanModifier.
"""

from finops_governor.estimator.base import CostModel
from finops_governor.gate.decision import GateDecision, Verdict
from finops_governor.gate.modifier import PlanModifier
from finops_governor.schemas import GenerationPlan
from finops_governor.validity.base import ValidityCheck
from finops_governor.validity.composition import resolve_verdict, summarize_findings
from finops_governor.validity.cost import CostCheck
from finops_governor.validity.models import CheckContext, Finding, ValidityReport


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
            # A modifiable finding guarantees the modifier can fit the plan
            # (single source of truth, established in the CostCheck).
            proposal = self._modifier.propose(plan, budget)
            return GateDecision.modify(
                plan.plan_id,
                estimate,
                budget,
                proposal.plan,
                proposal.estimate,
                proposal.modifications,
                reason=summarize_findings(report),
            )

        # APPROVE: clean uses the default reason; warnings are recorded for audit.
        if report.findings:
            return GateDecision.approve(
                plan.plan_id, estimate, budget, reason=summarize_findings(report)
            )
        return GateDecision.approve(plan.plan_id, estimate, budget)
