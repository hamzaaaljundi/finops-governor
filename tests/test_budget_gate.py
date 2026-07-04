"""Budget gate approve/block tests (M2, Task 2.5)."""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.estimator.estimate import CostEstimate
from finops_governor.gate import BudgetGate, Verdict
from finops_governor.schemas import GenerationPlan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plans" / "valid"


def _plan_with_budget(name: str, budget: float) -> GenerationPlan:
    data = json.loads((FIXTURES / name).read_text())
    data["budget"]["max_usd"] = budget
    return GenerationPlan.model_validate(data)


@pytest.fixture(scope="module")
def gate() -> BudgetGate:
    return BudgetGate(GpuRenderCostModel(get_profile("a10g")))


@pytest.fixture(scope="module")
def base_cost(gate) -> float:
    # cost of minimal.json under this gate's model
    return gate.evaluate(_plan_with_budget("minimal.json", 1_000)).estimate.total_usd


def test_under_budget_approves(gate):
    d = gate.evaluate(_plan_with_budget("minimal.json", 50))
    assert d.verdict is Verdict.APPROVE


def test_exactly_at_budget_approves(gate, base_cost):
    # boundary: cost == budget must APPROVE (<=)
    d = gate.evaluate(_plan_with_budget("minimal.json", base_cost))
    assert d.verdict is Verdict.APPROVE


def test_one_cent_over_blocks(gate, base_cost):
    # boundary: just under the cost must BLOCK
    d = gate.evaluate(_plan_with_budget("minimal.json", base_cost * 0.999))
    assert d.verdict is Verdict.BLOCK


def test_far_over_budget_blocks(gate):
    d = gate.evaluate(_plan_with_budget("multi_scene.json", 0.01))
    assert d.verdict is Verdict.BLOCK


def test_decision_carries_estimate_and_plan_id(gate):
    d = gate.evaluate(_plan_with_budget("minimal.json", 50))
    assert d.plan_id == "plan-minimal-001"
    assert d.estimate.total_images == 1


def test_gate_is_deterministic(gate):
    p = _plan_with_budget("multi_scene.json", 0.30)
    assert gate.evaluate(p).model_dump() == gate.evaluate(p).model_dump()


def test_gate_depends_only_on_cost_model_interface():
    # Any object satisfying CostModel works — proving the gate is decoupled from
    # the concrete GPU model (and thus substrate-agnostic).
    class FakeModel:
        def __init__(self, usd: float) -> None:
            self._usd = usd

        def estimate(self, plan: GenerationPlan) -> CostEstimate:
            return CostEstimate(
                total_usd=self._usd,
                total_gpu_hours=0.0,
                total_images=0,
                hardware_profile="fake",
                per_scene=[],
            )

    plan = _plan_with_budget("minimal.json", 100)
    assert BudgetGate(FakeModel(50)).evaluate(plan).verdict is Verdict.APPROVE
    assert BudgetGate(FakeModel(150)).evaluate(plan).verdict is Verdict.BLOCK
