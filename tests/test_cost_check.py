"""CostCheck tests (M3, Task 3.2).

The cost check wraps M2's estimator + modifier behind the ValidityCheck interface.
These tests confirm it conforms to the interface, emits the right findings, stays a
pure read, and - crucially - that its findings mirror the verdicts M2's BudgetGate
produced for the same plans (parity, proving nothing behavioural changed in the port).
"""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import BudgetGate, PlanModifier, Verdict
from finops_governor.schemas import GenerationPlan
from finops_governor.validity import (
    CheckContext,
    CostCheck,
    Severity,
    ValidityCheck,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plans" / "valid"


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


@pytest.fixture(scope="module")
def check(model) -> CostCheck:
    return CostCheck(PlanModifier(model))


def _context(model, name: str, budget: float) -> CheckContext:
    data = json.loads((FIXTURES / name).read_text())
    data["budget"]["max_usd"] = budget
    plan = GenerationPlan.model_validate(data)
    return CheckContext(plan=plan, cost_estimate=model.estimate(plan))


def test_conforms_to_interface(check):
    assert isinstance(check, ValidityCheck)
    assert check.name == "cost_budget"


def test_within_budget_is_clean(model, check):
    assert check.check(_context(model, "minimal.json", 50)) == []


def test_over_budget_recoverable_is_modifiable(model, check):
    findings = check.check(_context(model, "multi_scene.json", 0.20))
    assert len(findings) == 1
    assert findings[0].severity is Severity.MODIFIABLE
    assert findings[0].detail["recovered_usd"] <= 0.20


def test_over_budget_unrecoverable_is_blocking(model, check):
    findings = check.check(_context(model, "multi_scene.json", 0.001))
    assert len(findings) == 1
    assert findings[0].severity is Severity.BLOCKING


def test_finding_carries_audit_detail(model, check):
    findings = check.check(_context(model, "multi_scene.json", 0.20))
    detail = findings[0].detail
    assert detail["estimated_usd"] > detail["budget_usd"]
    assert findings[0].check_name == "cost_budget"


def test_check_does_not_mutate_the_plan(model, check):
    ctx = _context(model, "multi_scene.json", 0.20)
    before = ctx.plan.model_dump()
    check.check(ctx)
    assert ctx.plan.model_dump() == before  # pure read


# --- Parity: findings mirror M2 BudgetGate verdicts for the same plans ---


@pytest.mark.parametrize(
    "name, budget, expected_verdict, expected_severity",
    [
        ("minimal.json", 50, Verdict.APPROVE, None),
        ("multi_scene.json", 0.20, Verdict.MODIFY, Severity.MODIFIABLE),
        ("multi_scene.json", 0.001, Verdict.BLOCK, Severity.BLOCKING),
    ],
)
def test_findings_mirror_m2_gate(model, check, name, budget, expected_verdict, expected_severity):
    ctx = _context(model, name, budget)
    gate = BudgetGate(model, PlanModifier(model))
    verdict = gate.evaluate(ctx.plan).verdict
    findings = check.check(ctx)

    assert verdict is expected_verdict
    if expected_severity is None:
        assert findings == []
    else:
        assert findings[0].severity is expected_severity
