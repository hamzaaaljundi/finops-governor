"""Composed Governor tests (M3, Task 3.3)."""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import BudgetGate, PlanModifier, Verdict
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan
from finops_governor.validity import CheckContext, CostCheck, Finding, Severity

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plans" / "valid"


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


def _plan(name: str, budget: float) -> GenerationPlan:
    data = json.loads((FIXTURES / name).read_text())
    data["budget"]["max_usd"] = budget
    return GenerationPlan.model_validate(data)


# --- strict-superset parity: Governor([CostCheck]) == M2 BudgetGate ---


@pytest.mark.parametrize(
    "name, budget, expected",
    [
        ("minimal.json", 50, Verdict.APPROVE),
        ("multi_scene.json", 2500, Verdict.APPROVE),
        ("multi_scene.json", 0.20, Verdict.MODIFY),
        ("multi_scene.json", 0.001, Verdict.BLOCK),
    ],
)
def test_governor_matches_budget_gate(model, name, budget, expected):
    plan = _plan(name, budget)
    governor = Governor.with_cost_check(model)
    old_gate = BudgetGate(model, PlanModifier(model))

    decision = governor.evaluate(plan)
    assert decision.verdict is expected
    assert decision.verdict is old_gate.evaluate(plan).verdict


def test_modify_produces_valid_fitting_proposal(model):
    decision = Governor.with_cost_check(model).evaluate(_plan("multi_scene.json", 0.20))
    assert decision.verdict is Verdict.MODIFY
    assert decision.modified_estimate.total_usd <= decision.budget_usd
    assert isinstance(decision.modified_plan, GenerationPlan)


def test_governor_is_deterministic(model):
    plan = _plan("multi_scene.json", 0.20)
    gov = Governor.with_cost_check(model)
    assert gov.evaluate(plan).model_dump() == gov.evaluate(plan).model_dump()


# --- the interface pays off: a new check plugs in with no Governor change ---


class _AlwaysBlocks:
    name = "mock_block"

    def check(self, context: CheckContext) -> list[Finding]:
        return [Finding(check_name=self.name, severity=Severity.BLOCKING, reason="mock")]


class _AlwaysWarns:
    name = "mock_warn"

    def check(self, context: CheckContext) -> list[Finding]:
        return [Finding(check_name=self.name, severity=Severity.WARNING, reason="heads up")]


def test_a_second_check_can_block_an_affordable_plan(model):
    # affordable (cost clean) but a second axis blocks -> BLOCK, no Governor change
    modifier = PlanModifier(model)
    governor = Governor(model, [CostCheck(modifier), _AlwaysBlocks()], modifier)
    decision = governor.evaluate(_plan("minimal.json", 50))
    assert decision.verdict is Verdict.BLOCK
    assert "mock" in decision.reason


def test_warnings_do_not_block_but_are_recorded(model):
    modifier = PlanModifier(model)
    governor = Governor(model, [CostCheck(modifier), _AlwaysWarns()], modifier)
    decision = governor.evaluate(_plan("minimal.json", 50))
    assert decision.verdict is Verdict.APPROVE
    assert "heads up" in decision.reason
