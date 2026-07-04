"""Gate decision (verdict contract) tests (M2, Task 2.4)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import GateDecision, Verdict
from finops_governor.schemas import GenerationPlan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plans" / "valid"


def _load(name: str) -> GenerationPlan:
    return GenerationPlan.model_validate(json.loads((FIXTURES / name).read_text()))


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


@pytest.fixture(scope="module")
def big(model):  # ~$0.39
    return model.estimate(_load("multi_scene.json"))


@pytest.fixture(scope="module")
def small(model):  # ~$0.01
    return model.estimate(_load("minimal.json"))


def test_approve_factory(small):
    d = GateDecision.approve("p", small, 50)
    assert d.verdict is Verdict.APPROVE
    assert not d.modifications and d.modified_plan is None


def test_block_factory(big):
    d = GateDecision.block("p", big, 0.10)
    assert d.verdict is Verdict.BLOCK


def test_modify_factory(big, small):
    d = GateDecision.modify(
        "p", big, 0.30, _load("minimal.json"), small, ["reduced variation_count"]
    )
    assert d.verdict is Verdict.MODIFY
    assert d.modified_plan is not None
    assert d.modified_estimate.total_usd <= d.budget_usd


def test_approve_over_budget_rejected(big):
    with pytest.raises(ValidationError):
        GateDecision(
            verdict=Verdict.APPROVE,
            plan_id="p",
            reason="x",
            estimate=big,
            budget_usd=0.10,
        )


def test_approve_with_modification_rejected(small):
    with pytest.raises(ValidationError):
        GateDecision(
            verdict=Verdict.APPROVE,
            plan_id="p",
            reason="x",
            estimate=small,
            budget_usd=50,
            modifications=["oops"],
        )


def test_modify_without_modified_plan_rejected(big, small):
    with pytest.raises(ValidationError):
        GateDecision(
            verdict=Verdict.MODIFY,
            plan_id="p",
            reason="x",
            estimate=big,
            budget_usd=0.30,
            modified_estimate=small,
            modifications=["x"],
        )


def test_modify_over_budget_rejected(big, small):
    with pytest.raises(ValidationError):
        GateDecision.modify("p", big, 0.005, _load("minimal.json"), small, ["x"])


def test_block_with_modification_rejected(big):
    with pytest.raises(ValidationError):
        GateDecision(
            verdict=Verdict.BLOCK,
            plan_id="p",
            reason="x",
            estimate=big,
            budget_usd=0.10,
            modifications=["oops"],
        )


def test_default_reason_generated(small):
    assert "within" in GateDecision.approve("p", small, 50).reason


@pytest.mark.parametrize("build", ["approve", "block", "modify"])
def test_decision_round_trips_for_audit(build, big, small):
    if build == "approve":
        d = GateDecision.approve("p", small, 50)
    elif build == "block":
        d = GateDecision.block("p", big, 0.10)
    else:
        d = GateDecision.modify(
            "p", big, 0.30, _load("minimal.json"), small, ["reduced variations"]
        )
    assert GateDecision.model_validate_json(d.model_dump_json()) == d
