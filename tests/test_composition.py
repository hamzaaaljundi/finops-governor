"""Composition precedence tests (M3, Task 3.4).

Exhaustively verifies the severity precedence in isolation (pure function over mock
reports), then confirms the Governor honors it end-to-end for the key conflict case:
a plan that is cost-modifiable but blocked by another axis must BLOCK, not modify.
"""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import PlanModifier, Verdict
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan
from finops_governor.validity import (
    CheckContext,
    CostCheck,
    Finding,
    Severity,
    ValidityReport,
    resolve_verdict,
    summarize_findings,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plans" / "valid"


def _f(sev: Severity, name: str = "c") -> Finding:
    return Finding(check_name=name, severity=sev, reason=f"{name}-reason")


def _report(*severities: Severity) -> ValidityReport:
    return ValidityReport(findings=tuple(_f(s) for s in severities))


B, M, W = Severity.BLOCKING, Severity.MODIFIABLE, Severity.WARNING


# --- precedence policy, exhaustively (pure function) ---


@pytest.mark.parametrize(
    "severities, expected",
    [
        ((), Verdict.APPROVE),
        ((W,), Verdict.APPROVE),
        ((W, W), Verdict.APPROVE),
        ((M,), Verdict.MODIFY),
        ((M, W), Verdict.MODIFY),
        ((B,), Verdict.BLOCK),
        ((B, W), Verdict.BLOCK),
        ((B, M), Verdict.BLOCK),  # blocking dominates modifiable
        ((B, M, W), Verdict.BLOCK),
        ((B, B), Verdict.BLOCK),
        ((M, M), Verdict.MODIFY),
    ],
)
def test_precedence(severities, expected):
    assert resolve_verdict(_report(*severities)) is expected


def test_summary_lists_every_finding():
    report = ValidityReport(findings=(_f(B, "geometry"), _f(M, "cost_budget"), _f(W, "diversity")))
    summary = summarize_findings(report)
    assert "geometry" in summary
    assert "cost_budget" in summary
    assert "diversity" in summary
    assert summary.count("|") == 2  # three findings, two separators


# --- the Governor honors precedence for the key conflict case ---


class _AlwaysBlocks:
    name = "mock_geometry"

    def check(self, context: CheckContext) -> list[Finding]:
        return [Finding(check_name=self.name, severity=Severity.BLOCKING, reason="invalid")]


def test_blocking_axis_overrides_cost_modify(model_and_plan):
    model, plan = model_and_plan
    modifier = PlanModifier(model)
    # cost is over-budget-recoverable (would be MODIFY alone), geometry blocks
    governor = Governor(model, [CostCheck(modifier), _AlwaysBlocks()], modifier)
    decision = governor.evaluate(plan)
    assert decision.verdict is Verdict.BLOCK
    # audit records BOTH the blocking and the modifiable finding
    assert "mock_geometry" in decision.reason
    assert "cost_budget" in decision.reason


@pytest.fixture
def model_and_plan():
    model = GpuRenderCostModel(get_profile("a10g"))
    data = json.loads((FIXTURES / "multi_scene.json").read_text())
    data["budget"]["max_usd"] = 0.20  # over budget but recoverable
    return model, GenerationPlan.model_validate(data)
