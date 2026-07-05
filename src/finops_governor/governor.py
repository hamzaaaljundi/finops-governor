"""The Governor - the composed multi-axis gate (M3, Task 3.3).

Runs every registered validity check over a plan, aggregates their findings into one
ValidityReport, and composes that into a single approve / modify / block decision.

Depends only on the ValidityCheck interface, so new axes (diversity M4, USD geometry M5)
register without changing this class. With a single CostCheck registered, it reproduces
the M2 BudgetGate behavior exactly - the composed gate is a strict superset of the old
budget gate, which is what makes "budget and geometry are one gate" literally true.

Composition precedence (formalized in Task 3.4): a BLOCKING finding dominates; else a
MODIFIABLE finding yields MODIFY; else APPROVE (warnings are recorded, not decisive).
Only the cost axis can produce a MODIFY (decision 2), so the modify proposal is built by
the PlanModifier.
"""

from finops_governor.estimator.base import CostModel
from finops_governor.gate.decision import GateDecision
from finops_governor.gate.modifier import PlanModifier
from finops_governor.schemas import GenerationPlan
from finops_governor.validity.base import ValidityCheck
from finops_governor.validity.cost import CostCheck
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

    def evaluate(self, plan: GenerationPlan) -> GateDecision:
        estimate = self._cost_model.estimate(plan)
        context = CheckContext(plan=plan, cost_estimate=estimate)

        findings: list[Finding] = []
        for check in self._checks:
            findings.extend(check.check(context))
        report = ValidityReport(findings=tuple(findings))

        budget = plan.budget.max_usd

        if report.has_blocking:
            return GateDecision.block(
                plan.plan_id,
                estimate,
                budget,
                reason=self._summarize(report, Severity.BLOCKING),
            )

        if report.has_modifiable:
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
                reason=self._summarize(report, Severity.MODIFIABLE),
            )

        if report.warnings:
            reason = "Approved with warnings: " + " ".join(
                w.reason for w in report.warnings
            )
            return GateDecision.approve(plan.plan_id, estimate, budget, reason=reason)

        return GateDecision.approve(plan.plan_id, estimate, budget)

    @staticmethod
    def _summarize(report: ValidityReport, severity: Severity) -> str:
        return " ".join(f.reason for f in report.findings if f.severity is severity)
