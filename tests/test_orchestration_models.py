"""Pipeline state and audit contract tests (M7, Task 7.2)."""

import json

import pytest
from pydantic import ValidationError

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import Verdict
from finops_governor.governor import Governor
from finops_governor.orchestration import AuditEvent, PipelineState, PipelineStatus
from finops_governor.schemas import GenerationPlan


def _plan() -> GenerationPlan:
    return GenerationPlan.model_validate(
        {
            "plan_id": "p",
            "scenes": [
                {
                    "scene_id": "s",
                    "environment": {"asset_id": "e", "usd_path": "e.usda"},
                    "assets": [{"asset_id": "a", "usd_path": "a.usda"}],
                    "cameras": [{"camera_id": "c", "transform": {}}],
                    "variation_count": 10,
                }
            ],
            "modalities": ["RGB"],
            "render_settings": {"width": 1280, "height": 720},
            "budget": {"max_usd": 50},
        }
    )


def test_initial_state_defaults():
    state = PipelineState(request="500 arm variations", budget_usd=50.0)
    assert state.status is PipelineStatus.RUNNING
    assert state.plan is None and state.decision is None
    assert state.gate_passes == 0
    assert state.events == ()


def test_state_is_frozen():
    state = PipelineState(budget_usd=50.0)
    with pytest.raises(ValidationError):
        state.status = PipelineStatus.EXECUTED


def test_event_is_frozen_and_rejects_extras():
    event = AuditEvent(sequence=0, node="plan", summary="planned")
    with pytest.raises(ValidationError):
        event.node = "gate"
    with pytest.raises(ValidationError):
        AuditEvent(sequence=0, node="plan", summary="s", unexpected=True)


def test_with_event_appends_and_sequences_without_mutation():
    s0 = PipelineState(budget_usd=50.0)
    s1 = s0.with_event("plan", "planned the job")
    s2 = s1.with_event("gate", "gated the plan", verdict=Verdict.APPROVE)
    assert s0.events == ()  # original untouched
    assert [e.sequence for e in s2.events] == [0, 1]
    assert [e.node for e in s2.events] == ["plan", "gate"]
    assert s2.events[1].verdict is Verdict.APPROVE


def test_with_event_updates_state_fields_in_the_same_step():
    s0 = PipelineState(budget_usd=50.0)
    s1 = s0.with_event("plan", "planned", plan=_plan(), gate_passes=1)
    assert s1.plan is not None and s1.gate_passes == 1
    assert s0.plan is None


def test_timestamps_are_utc():
    event = AuditEvent(sequence=0, node="plan", summary="s")
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset().total_seconds() == 0


def test_full_state_round_trips_with_nested_decision():
    plan = _plan()
    model = GpuRenderCostModel(get_profile("a10g"))
    decision = Governor.with_default_checks(model).evaluate(plan)
    state = (
        PipelineState(request="req", budget_usd=50.0)
        .with_event("plan", "planned", plan=plan)
        .with_event(
            "gate",
            "gated",
            verdict=decision.verdict,
            driving_axes=("cost_budget",),
            estimated_usd=decision.estimate.total_usd,
            budget_usd=50.0,
            decision=decision,
            gate_passes=1,
        )
        .with_event("execute", "executed", status=PipelineStatus.EXECUTED)
    )
    restored = PipelineState.model_validate(json.loads(state.model_dump_json()))
    assert restored == state
    assert restored.status is PipelineStatus.EXECUTED
    assert restored.events[1].driving_axes == ("cost_budget",)


def test_terminal_status_values():
    assert {s.value for s in PipelineStatus} == {
        "RUNNING",
        "EXECUTED",
        "BLOCKED",
        "FAILED",
    }
