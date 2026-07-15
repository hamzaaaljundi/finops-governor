"""Node function tests (M7, Task 7.3) - each node in isolation, plus the router.

Includes the regression that matters: after adoption, the router must send the state
back to the gate, never into a second adoption of a stale decision.
"""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import Verdict
from finops_governor.governor import Governor
from finops_governor.orchestration import (
    OrchestrationError,
    PipelineState,
    PipelineStatus,
    adopt_node,
    execute_node,
    gate_node,
    plan_node,
    route,
)
from finops_governor.planner import FakePlannerModel, Planner
from finops_governor.schemas import GenerationPlan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def governor() -> Governor:
    return Governor.with_default_checks(GpuRenderCostModel(get_profile("a10g")))


def _plan_dict(budget: float = 50.0, variation_count: int = 10) -> dict:
    return {
        "plan_id": "p1",
        "scenes": [
            {
                "scene_id": "s1",
                "environment": {"asset_id": "e", "usd_path": "e.usda"},
                "assets": [{"asset_id": "a", "usd_path": "a.usda"}],
                "cameras": [{"camera_id": "c", "transform": {}}],
                "variation_count": variation_count,
            }
        ],
        "modalities": ["RGB"],
        "render_settings": {"width": 1280, "height": 720},
        "budget": {"max_usd": budget},
    }


def _redundant_plan() -> GenerationPlan:
    return GenerationPlan.model_validate(
        json.loads(
            (FIXTURES / "diversity" / "redundant" / "production_scale.json").read_text()
        )
    )


# --- plan_node ---


def test_plan_node_success():
    planner = Planner(FakePlannerModel([json.dumps(_plan_dict())]))
    s0 = PipelineState(request="10 variations", budget_usd=50.0)
    s1 = plan_node(s0, planner)
    assert s1.plan is not None and s1.plan.plan_id == "p1"
    assert s1.status is PipelineStatus.RUNNING
    assert s1.events[-1].node == "plan"
    assert s0.plan is None  # purity


def test_plan_node_failure_sets_failed_with_audit():
    planner = Planner(FakePlannerModel(["bad", "bad", "bad"]))
    s1 = plan_node(PipelineState(request="req", budget_usd=50.0), planner)
    assert s1.status is PipelineStatus.FAILED
    assert s1.error is not None
    assert "planning failed" in s1.events[-1].summary


def test_plan_node_requires_a_request():
    with pytest.raises(OrchestrationError, match="request"):
        plan_node(PipelineState(budget_usd=50.0), Planner(FakePlannerModel([])))


# --- gate_node ---


def test_gate_node_approve(governor):
    plan = GenerationPlan.model_validate(_plan_dict())
    s1 = gate_node(PipelineState(budget_usd=50.0, plan=plan), governor)
    assert s1.decision.verdict is Verdict.APPROVE
    assert s1.gate_passes == 1
    assert s1.events[-1].driving_axes is None  # no decisive findings on approve


def test_gate_node_modify_attributes_the_diversity_axis(governor):
    s1 = gate_node(
        PipelineState(budget_usd=1_000_000.0, plan=_redundant_plan()), governor
    )
    assert s1.decision.verdict is Verdict.MODIFY
    assert s1.events[-1].driving_axes == ("diversity",)


def test_gate_node_block_sets_blocked_and_attributes_cost(governor):
    plan = GenerationPlan.model_validate(_plan_dict(budget=0.000001))
    s1 = gate_node(PipelineState(budget_usd=0.000001, plan=plan), governor)
    assert s1.decision.verdict is Verdict.BLOCK
    assert s1.status is PipelineStatus.BLOCKED
    assert s1.events[-1].driving_axes == ("cost_budget",)


def test_gate_node_requires_a_plan(governor):
    with pytest.raises(OrchestrationError, match="plan"):
        gate_node(PipelineState(budget_usd=50.0), governor)


# --- adopt_node ---


def test_adopt_node_swaps_in_the_proposal_and_clears_the_decision(governor):
    s1 = gate_node(
        PipelineState(budget_usd=1_000_000.0, plan=_redundant_plan()), governor
    )
    s2 = adopt_node(s1)
    assert s2.plan.scenes[0].variation_count == 26  # the justified count
    assert s2.decision is None  # stale decision cleared
    assert "saved" in s2.events[-1].summary
    assert s2.events[-1].detail["modifications"]  # the trims, attributable
    assert s1.plan.scenes[0].variation_count == 50_000  # purity


def test_adopt_node_requires_a_modify_decision(governor):
    plan = GenerationPlan.model_validate(_plan_dict())
    approved = gate_node(PipelineState(budget_usd=50.0, plan=plan), governor)
    with pytest.raises(OrchestrationError, match="MODIFY"):
        adopt_node(approved)


# --- execute_node ---


def test_execute_node_records_the_job_and_finishes(governor):
    plan = GenerationPlan.model_validate(_plan_dict())
    s1 = gate_node(PipelineState(budget_usd=50.0, plan=plan), governor)
    s2 = execute_node(s1)
    assert s2.status is PipelineStatus.EXECUTED
    assert s2.events[-1].detail["images"] == 10
    assert "would render" in s2.events[-1].summary


def test_execute_node_requires_an_approve_decision(governor):
    s1 = gate_node(
        PipelineState(budget_usd=1_000_000.0, plan=_redundant_plan()), governor
    )
    with pytest.raises(OrchestrationError, match="APPROVE"):
        execute_node(s1)


# --- the router ---


def test_route_full_mapping(governor):
    fresh = PipelineState(
        budget_usd=50.0, plan=GenerationPlan.model_validate(_plan_dict())
    )
    assert route(fresh) == "gate"

    approved = gate_node(fresh, governor)
    assert route(approved) == "execute"

    modify = gate_node(
        PipelineState(budget_usd=1_000_000.0, plan=_redundant_plan()), governor
    )
    assert route(modify) == "adopt"
    assert route(adopt_node(modify)) == "gate"  # the regression: never adopt twice

    blocked = gate_node(
        PipelineState(
            budget_usd=0.000001,
            plan=GenerationPlan.model_validate(_plan_dict(budget=0.000001)),
        ),
        governor,
    )
    assert route(blocked) == "halt"

    failed = PipelineState(budget_usd=50.0, status=PipelineStatus.FAILED, error="x")
    assert route(failed) == "halt"

    executed = execute_node(approved)
    assert route(executed) == "halt"
