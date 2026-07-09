"""Planner core tests (M6, Task 6.3).

Every path of the deterministic loop around the stochastic call, driven by the scripted
fake: first-try success, prompt contract, budget enforcement, fence tolerance, repair on
malformed JSON and on schema violations (with the error verifiably fed back), bounded
exhaustion, and the plan flowing straight into the Governor.
"""

import json

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import Verdict
from finops_governor.governor import Governor
from finops_governor.planner import FakePlannerModel, Planner, PlannerError
from finops_governor.schemas import GenerationPlan


def _valid_plan_json(budget: float = 50.0, **overrides) -> str:
    data = {
        "plan_id": "p1",
        "scenes": [
            {
                "scene_id": "s1",
                "environment": {"asset_id": "floor", "usd_path": "floor.usda"},
                "assets": [{"asset_id": "arm", "usd_path": "arm.usda"}],
                "cameras": [{"camera_id": "cam", "transform": {}}],
                "variation_count": 500,
                "randomization": {"parameters": [{"name": "az", "levels": 12}]},
            }
        ],
        "modalities": ["RGB", "DEPTH"],
        "render_settings": {"width": 1280, "height": 720},
        "budget": {"max_usd": budget},
    }
    data.update(overrides)
    return json.dumps(data)


# --- success path and the prompt contract ---


def test_first_try_success_makes_one_call():
    fake = FakePlannerModel([_valid_plan_json()])
    plan = Planner(fake).plan("500 arm variations", budget_usd=50.0)
    assert isinstance(plan, GenerationPlan)
    assert fake.calls == 1


def test_prompt_contains_the_contract():
    fake = FakePlannerModel([_valid_plan_json()])
    Planner(fake).plan("robotic arm on an assembly floor", budget_usd=75.0)
    prompt = fake.prompts[0]
    assert "GenerationPlan" in prompt or "properties" in prompt  # the live schema
    assert "robotic arm on an assembly floor" in prompt  # the delimited request
    assert "<request>" in prompt
    assert "75.0" in prompt  # the caller's budget
    assert "Never inflate `levels`" in prompt  # the honesty instruction


def test_budget_is_enforced_by_code_not_the_model():
    # the model claims a 999 budget; the caller said 50 - code wins
    fake = FakePlannerModel([_valid_plan_json(budget=999.0)])
    plan = Planner(fake).plan("req", budget_usd=50.0)
    assert plan.budget.max_usd == 50.0


def test_fenced_json_is_tolerated_without_a_repair_round():
    fenced = f"```json\n{_valid_plan_json()}\n```"
    fake = FakePlannerModel([fenced])
    plan = Planner(fake).plan("req", budget_usd=50.0)
    assert isinstance(plan, GenerationPlan)
    assert fake.calls == 1


# --- the repair loop ---


def test_repairs_malformed_json_and_feeds_error_back():
    fake = FakePlannerModel(["this is not json", _valid_plan_json()])
    plan = Planner(fake).plan("req", budget_usd=50.0)
    assert isinstance(plan, GenerationPlan)
    assert fake.calls == 2
    repair_prompt = fake.prompts[1]
    assert "this is not json" in repair_prompt  # previous output included
    assert "Expecting value" in repair_prompt  # verbatim JSON error included


def test_repairs_schema_violation_and_feeds_error_back():
    bad = _valid_plan_json(hallucinated_field=True)
    fake = FakePlannerModel([bad, _valid_plan_json()])
    plan = Planner(fake).plan("req", budget_usd=50.0)
    assert isinstance(plan, GenerationPlan)
    assert (
        "Extra inputs are not permitted" in fake.prompts[1]
    )  # pydantic error verbatim


def test_two_failures_then_success_uses_all_three_attempts():
    fake = FakePlannerModel(["garbage", "{}", _valid_plan_json()])
    plan = Planner(fake).plan("req", budget_usd=50.0)
    assert isinstance(plan, GenerationPlan)
    assert fake.calls == 3


# --- bounded failure ---


def test_exhaustion_raises_planner_error_after_exactly_max_attempts():
    fake = FakePlannerModel(["bad", "bad", "bad"])
    with pytest.raises(PlannerError, match="3 attempts"):
        Planner(fake).plan("req", budget_usd=50.0)
    assert fake.calls == 3  # never a fourth call


def test_max_attempts_is_tunable():
    fake = FakePlannerModel(["bad"])
    with pytest.raises(PlannerError, match="1 attempts"):
        Planner(fake, max_attempts=1).plan("req", budget_usd=50.0)
    assert fake.calls == 1


# --- the trust boundary, end to end ---


def test_planned_output_flows_straight_into_the_governor():
    fake = FakePlannerModel([_valid_plan_json()])
    plan = Planner(fake).plan("500 arm variations under 50 dollars", budget_usd=50.0)
    model = GpuRenderCostModel(get_profile("a10g"))
    decision = Governor.with_default_checks(model).evaluate(plan)
    assert decision.verdict in (Verdict.APPROVE, Verdict.MODIFY, Verdict.BLOCK)
    assert decision.plan_id == plan.plan_id
