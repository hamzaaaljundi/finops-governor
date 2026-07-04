"""End-to-end gate decision-space tests (M2, Task 2.7).

Drives named scenario fixtures through the FULL pipeline (cost estimator + budget gate +
modifier) and asserts each lands on its expected verdict. Fixtures live under
fixtures/gate/<verdict>/, so the folder name IS the expected verdict — adding a scenario
is just dropping a file in the right folder, no test change required.

These complement the per-component unit tests: this suite proves the assembled governor
produces the correct decision for each category of job.
"""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import BudgetGate, PlanModifier, Verdict
from finops_governor.schemas import GenerationPlan

SCENARIOS = Path(__file__).resolve().parents[1] / "fixtures" / "gate"


def _cases(verdict: str) -> list[Path]:
    return sorted((SCENARIOS / verdict).glob("*.json"))


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


@pytest.fixture(scope="module")
def gate() -> BudgetGate:
    model = GpuRenderCostModel(get_profile("a10g"))
    return BudgetGate(model, PlanModifier(model))


def _evaluate(gate: BudgetGate, path: Path):
    plan = GenerationPlan.model_validate(json.loads(path.read_text()))
    return gate.evaluate(plan)


def test_scenarios_discovered():
    assert _cases("approve") and _cases("modify") and _cases("block")


@pytest.mark.parametrize("path", _cases("approve"), ids=_id)
def test_approve_scenarios(gate, path):
    d = _evaluate(gate, path)
    assert d.verdict is Verdict.APPROVE
    assert d.estimate.total_usd <= d.budget_usd


@pytest.mark.parametrize("path", _cases("modify"), ids=_id)
def test_modify_scenarios(gate, path):
    d = _evaluate(gate, path)
    assert d.verdict is Verdict.MODIFY
    # a modify must produce a cheaper, budget-fitting, still-valid plan
    assert d.modified_estimate.total_usd <= d.budget_usd
    assert d.estimate.total_usd > d.budget_usd
    assert isinstance(d.modified_plan, GenerationPlan)
    assert d.modifications


@pytest.mark.parametrize("path", _cases("block"), ids=_id)
def test_block_scenarios(gate, path):
    d = _evaluate(gate, path)
    assert d.verdict is Verdict.BLOCK
    assert d.estimate.total_usd > d.budget_usd


def test_every_decision_is_auditable(gate):
    # every scenario's decision must round-trip losslessly for the M5 audit log
    for verdict in ("approve", "modify", "block"):
        for path in _cases(verdict):
            from finops_governor.gate import GateDecision

            d = _evaluate(gate, path)
            assert GateDecision.model_validate_json(d.model_dump_json()) == d
