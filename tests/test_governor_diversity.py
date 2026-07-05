"""Governor + diversity integration tests (M4, Task 4.3).

Confirms diversity (a WARNING axis) never changes the cost-driven verdict but is always
recorded in the decision's audit reason - the multi-axis composition working end-to-end.
"""

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan
from finops_governor.gate import Verdict


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


@pytest.fixture(scope="module")
def governor(model) -> Governor:
    return Governor.with_default_checks(model)


def _plan(budget: float, variation_count: int = 5000, declared: bool = True):
    scene = {
        "scene_id": "s",
        "environment": {"asset_id": "e", "usd_path": "e.usda"},
        "assets": [{"asset_id": "a", "usd_path": "a.usda"}],
        "cameras": [{"camera_id": "c", "transform": {}}],
        "variation_count": variation_count,
    }
    if declared:
        scene["randomization"] = {
            "parameters": [{"name": "az", "levels": 12}, {"name": "pose", "levels": 8}]
        }
    return GenerationPlan.model_validate(
        {
            "plan_id": "p",
            "scenes": [scene],
            "modalities": ["RGB", "DEPTH", "SEMANTIC_SEGMENTATION"],
            "render_settings": {"width": 1920, "height": 1080},
            "budget": {"max_usd": budget},
        }
    )


def test_default_wiring_has_both_axes(model):
    # smoke: the factory builds a governor that flags redundancy
    decision = Governor.with_default_checks(model).evaluate(_plan(50))
    assert "diversity" in decision.reason


def test_redundant_but_affordable_approves_with_warning(governor):
    decision = governor.evaluate(_plan(50))
    assert decision.verdict is Verdict.APPROVE  # warning does not block
    assert "diversity" in decision.reason  # but is recorded
    assert "wasted" in decision.reason or "redundant" in decision.reason


def test_redundant_and_over_budget_recoverable_modifies(governor):
    decision = governor.evaluate(_plan(1.0))
    assert decision.verdict is Verdict.MODIFY  # cost drives the verdict
    assert "diversity" in decision.reason  # diversity still recorded
    assert "cost_budget" in decision.reason


def test_redundant_and_unrecoverable_blocks(governor):
    decision = governor.evaluate(_plan(0.001))
    assert decision.verdict is Verdict.BLOCK
    assert "diversity" in decision.reason


def test_efficient_plan_has_no_diversity_finding(governor):
    decision = governor.evaluate(_plan(50, variation_count=50))
    assert decision.verdict is Verdict.APPROVE
    assert "diversity" not in decision.reason


def test_undeclared_randomization_has_no_diversity_finding(governor):
    decision = governor.evaluate(_plan(50, variation_count=100_000, declared=False))
    assert "diversity" not in decision.reason


def test_diversity_does_not_change_cost_only_verdict(model):
    # a governor with cost only vs cost+diversity must agree on the VERDICT
    cost_only = Governor.with_cost_check(model)
    both = Governor.with_default_checks(model)
    for budget in (50, 1.0, 0.001):
        plan = _plan(budget)
        assert cost_only.evaluate(plan).verdict is both.evaluate(plan).verdict


def test_decision_round_trips_with_diversity(governor):
    from finops_governor.gate import GateDecision

    decision = governor.evaluate(_plan(50))
    assert GateDecision.model_validate_json(decision.model_dump_json()) == decision
