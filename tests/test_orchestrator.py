"""Orchestrator tests (M7, Task 7.4) - every terminal state, the trail's story,
and the loud bound."""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import Verdict
from finops_governor.governor import Governor
from finops_governor.orchestration import Orchestrator, PipelineState, PipelineStatus
from finops_governor.planner import FakePlannerModel, Planner
from finops_governor.schemas import GenerationPlan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def governor() -> Governor:
    return Governor.with_default_checks(GpuRenderCostModel(get_profile("a10g")))


def _plan_json(budget=50.0, variation_count=10, levels=None) -> str:
    scene = {
        "scene_id": "s1",
        "environment": {"asset_id": "e", "usd_path": "e.usda"},
        "assets": [{"asset_id": "a", "usd_path": "a.usda"}],
        "cameras": [{"camera_id": "c", "transform": {}}],
        "variation_count": variation_count,
    }
    if levels:
        scene["randomization"] = {
            "parameters": [{"name": f"p{i}", "levels": v} for i, v in enumerate(levels)]
        }
    return json.dumps(
        {
            "plan_id": "p1",
            "scenes": [scene],
            "modalities": ["RGB"],
            "render_settings": {"width": 1280, "height": 720},
            "budget": {"max_usd": budget},
        }
    )


def _orch(governor, responses) -> Orchestrator:
    return Orchestrator(Planner(FakePlannerModel(responses)), governor)


# --- the three terminal states ---


def test_approve_path(governor):
    final = _orch(governor, [_plan_json()]).run("10 variations", budget_usd=50.0)
    assert final.status is PipelineStatus.EXECUTED
    assert [e.node for e in final.events] == ["plan", "gate", "execute"]
    assert final.gate_passes == 1


def test_value_trim_path_executes_the_trimmed_plan(governor):
    final = _orch(governor, [_plan_json(variation_count=50_000, levels=[4, 4])]).run(
        "50k arm variations", budget_usd=1000.0
    )
    assert final.status is PipelineStatus.EXECUTED
    assert [e.node for e in final.events] == [
        "plan",
        "gate",
        "adopt",
        "gate",
        "execute",
    ]
    assert final.gate_passes == 2  # the verified convergence: exactly one extra pass
    assert final.plan.scenes[0].variation_count == 26
    assert "saved" in final.events[2].summary


def test_block_path_is_a_successful_governance_outcome(governor):
    final = _orch(governor, [_plan_json(budget=0.000001)]).run(
        "impossible", budget_usd=0.000001
    )
    assert final.status is PipelineStatus.BLOCKED
    assert final.error is None  # blocked is not failed
    assert final.events[-1].node == "gate"
    assert final.events[-1].driving_axes == ("cost_budget",)


def test_planner_exhaustion_fails_with_trail(governor):
    final = _orch(governor, ["bad", "bad", "bad"]).run("req", budget_usd=50.0)
    assert final.status is PipelineStatus.FAILED
    assert final.error is not None
    assert final.events[-1].node == "plan"


# --- the loud bound ---


def test_non_converging_governor_hits_the_bound_loudly(governor):
    real_decision = governor.evaluate(
        GenerationPlan.model_validate(
            json.loads(_plan_json(variation_count=50_000, levels=[4, 4]))
        )
    )
    assert real_decision.verdict is Verdict.MODIFY

    class NeverConverges:
        """Pathological gate: every plan, including its own proposal, gets MODIFY."""

        def evaluate(self, plan):
            return real_decision

    orch = Orchestrator(
        Planner(FakePlannerModel([_plan_json(variation_count=50_000, levels=[4, 4])])),
        NeverConverges(),
        max_gate_passes=3,
    )
    final = orch.run("req", budget_usd=1000.0)
    assert final.status is PipelineStatus.FAILED
    assert "converge" in final.error
    assert final.gate_passes == 3  # never a fourth pass
    assert "invariant violation" in final.events[-1].summary


# --- run_plan and the trail as artifact ---


def test_run_plan_skips_the_planner(governor):
    plan = GenerationPlan.model_validate(
        json.loads(
            (FIXTURES / "diversity" / "redundant" / "production_scale.json").read_text()
        )
    )
    final = Orchestrator(Planner(FakePlannerModel([])), governor).run_plan(plan)
    assert final.status is PipelineStatus.EXECUTED
    assert final.events[0].node == "gate"  # no plan event
    assert final.plan.scenes[0].variation_count == 26


def test_terminal_state_serializes_as_the_audit_artifact(governor):
    final = _orch(governor, [_plan_json(variation_count=50_000, levels=[4, 4])]).run(
        "req", budget_usd=1000.0
    )
    restored = PipelineState.model_validate(json.loads(final.model_dump_json()))
    assert restored == final
    adopt = restored.events[2]
    assert adopt.detail["modifications"][0].startswith("value:")  # attributable savings
