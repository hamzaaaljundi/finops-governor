"""Governor + diversity integration tests (M4; value-aware semantics in M6.5, ADR 0007).

The diversity axis is MODIFIABLE: a redundant plan yields MODIFY with a value-trimmed
proposal. The proposal is built in two ordered passes - value first (free), budget only
if still needed (costs signal).
"""

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import Verdict
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan


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


def test_redundant_affordable_plan_gets_value_trimmed(governor):
    decision = governor.evaluate(_plan(50))
    assert decision.verdict is Verdict.MODIFY
    assert "diversity" in decision.reason
    mods = " ".join(decision.modifications)
    assert "value:" in mods and "expected-coverage trim" in mods
    assert "budget:" not in mods  # value pass alone sufficed
    # the proposal preserves the coverage bar at a fraction of the cost
    assert decision.modified_plan.scenes[0].variation_count < 5000
    assert decision.modified_estimate.total_usd < decision.estimate.total_usd


def test_value_trim_target_is_the_justified_count(governor):
    decision = governor.evaluate(_plan(50))
    trimmed = decision.modified_plan.scenes[0].variation_count
    # capacity 96 at threshold 0.5 -> justified count is 153 (verified boundary)
    assert trimmed == 153


def test_redundant_and_over_budget_uses_both_passes_in_order(governor):
    # budget forces a cost finding too; the proposal must trim value FIRST,
    # then budget only if still over
    decision = governor.evaluate(_plan(0.05))
    assert decision.verdict is Verdict.MODIFY
    mods = decision.modifications
    assert any(m.startswith("value:") for m in mods)
    value_idx = next(i for i, m in enumerate(mods) if m.startswith("value:"))
    budget_idxs = [i for i, m in enumerate(mods) if m.startswith("budget:")]
    assert all(i > value_idx for i in budget_idxs)  # value pass recorded first
    assert decision.modified_estimate.total_usd <= decision.budget_usd


def test_value_trim_can_rescue_an_over_budget_plan_without_cutting_signal(governor):
    # over budget as-planned, but the value-trimmed plan fits: no budget pass needed
    decision = governor.evaluate(_plan(0.10))
    assert decision.verdict is Verdict.MODIFY
    mods = " ".join(decision.modifications)
    assert "value:" in mods
    assert "budget:" not in mods
    assert decision.modified_estimate.total_usd <= 0.10


def test_redundant_and_unrecoverable_still_blocks(governor):
    decision = governor.evaluate(_plan(0.000001))
    assert decision.verdict is Verdict.BLOCK  # below even the 1-variation floor
    assert "diversity" in decision.reason


def test_efficient_plan_still_approves_untouched(governor):
    decision = governor.evaluate(_plan(50, variation_count=50))
    assert decision.verdict is Verdict.APPROVE
    assert "diversity" not in decision.reason


def test_undeclared_randomization_is_never_trimmed(governor):
    decision = governor.evaluate(_plan(50, variation_count=100_000, declared=False))
    assert decision.verdict is Verdict.APPROVE
    assert "diversity" not in decision.reason


def test_proposal_round_trips_for_audit(governor):
    from finops_governor.gate import GateDecision

    decision = governor.evaluate(_plan(50))
    assert GateDecision.model_validate_json(decision.model_dump_json()) == decision
