"""Plan modifier + gate modify-path tests (M2, Task 2.6)."""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import BudgetGate, PlanModifier, Verdict
from finops_governor.schemas import GenerationPlan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plans" / "valid"


def _plan_with_budget(name: str, budget: float) -> GenerationPlan:
    data = json.loads((FIXTURES / name).read_text())
    data["budget"]["max_usd"] = budget
    return GenerationPlan.model_validate(data)


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


@pytest.fixture(scope="module")
def modifier(model) -> PlanModifier:
    return PlanModifier(model)


@pytest.fixture(scope="module")
def min_cost(model) -> float:
    # cost of multi_scene with all variation counts at 1
    data = json.loads((FIXTURES / "multi_scene.json").read_text())
    for s in data["scenes"]:
        s["variation_count"] = 1
    return model.estimate(GenerationPlan.model_validate(data)).total_usd


def test_proposal_fits_budget(modifier):
    plan = _plan_with_budget("multi_scene.json", 0.20)
    proposal = modifier.propose(plan, 0.20)
    assert proposal is not None
    assert proposal.estimate.total_usd <= 0.20


def test_proposal_reduces_variations_and_stays_valid(modifier):
    plan = _plan_with_budget("multi_scene.json", 0.20)
    proposal = modifier.propose(plan, 0.20)
    # a real GenerationPlan (re-validated) with reduced counts
    assert isinstance(proposal.plan, GenerationPlan)
    for original, modified in zip(plan.scenes, proposal.plan.scenes):
        assert modified.variation_count <= original.variation_count
    assert proposal.modifications  # non-empty change log


def test_proportions_preserved(modifier):
    # both scenes should be reduced, not just one — proportional scaling
    plan = _plan_with_budget("multi_scene.json", 0.20)
    proposal = modifier.propose(plan, 0.20)
    reduced = [
        m.variation_count < o.variation_count for o, m in zip(plan.scenes, proposal.plan.scenes)
    ]
    assert all(reduced)


def test_unrecoverable_returns_none(modifier, min_cost):
    # budget below the minimum viable plan cannot be recovered
    plan = _plan_with_budget("multi_scene.json", min_cost * 0.5)
    assert modifier.propose(plan, min_cost * 0.5) is None


def test_modifier_is_deterministic(modifier):
    plan = _plan_with_budget("multi_scene.json", 0.20)
    a = modifier.propose(plan, 0.20)
    b = modifier.propose(plan, 0.20)
    assert a.plan.model_dump() == b.plan.model_dump()


def test_gate_modifies_when_recoverable(model, modifier):
    gate = BudgetGate(model, modifier)
    decision = gate.evaluate(_plan_with_budget("multi_scene.json", 0.20))
    assert decision.verdict is Verdict.MODIFY
    assert decision.modified_estimate.total_usd <= decision.budget_usd


def test_gate_blocks_when_unrecoverable(model, modifier, min_cost):
    gate = BudgetGate(model, modifier)
    decision = gate.evaluate(_plan_with_budget("multi_scene.json", min_cost * 0.5))
    assert decision.verdict is Verdict.BLOCK


def test_gate_without_modifier_still_blocks(model):
    # Task 2.5 behavior preserved when no modifier is injected
    gate = BudgetGate(model)
    decision = gate.evaluate(_plan_with_budget("multi_scene.json", 0.20))
    assert decision.verdict is Verdict.BLOCK
