"""End-to-end Governor scenario suite (M3, Task 3.5).

Two acceptance proofs for the assembled multi-axis Governor:

1. Corpus parity - the Governor (cost axis only) drives the entire M2 decision-space
   fixture corpus (fixtures/gate/<verdict>/) to the correct verdict, proving it is a
   drop-in replacement for the old BudgetGate across every scenario.
2. Multi-axis composition end-to-end - with a second (mock) check registered, the full
   pipeline composes both axes into one decision, and every decision is auditable.
"""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import GateDecision, PlanModifier, Verdict
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan
from finops_governor.validity import CheckContext, CostCheck, Finding, Severity

SCENARIOS = Path(__file__).resolve().parents[1] / "fixtures" / "gate"


def _cases(verdict: str) -> list[Path]:
    return sorted((SCENARIOS / verdict).glob("*.json"))


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


@pytest.fixture(scope="module")
def governor(model) -> Governor:
    return Governor.with_cost_check(model)


def _load(path: Path) -> GenerationPlan:
    return GenerationPlan.model_validate(json.loads(path.read_text()))


# --- corpus parity: the assembled Governor handles the whole decision space ---


def test_scenarios_discovered():
    assert _cases("approve") and _cases("modify") and _cases("block")


@pytest.mark.parametrize("path", _cases("approve"), ids=_id)
def test_approve_corpus(governor, path):
    assert governor.evaluate(_load(path)).verdict is Verdict.APPROVE


@pytest.mark.parametrize("path", _cases("modify"), ids=_id)
def test_modify_corpus(governor, path):
    d = governor.evaluate(_load(path))
    assert d.verdict is Verdict.MODIFY
    assert d.modified_estimate.total_usd <= d.budget_usd


@pytest.mark.parametrize("path", _cases("block"), ids=_id)
def test_block_corpus(governor, path):
    assert governor.evaluate(_load(path)).verdict is Verdict.BLOCK


# --- multi-axis composition, end-to-end ---


class _MockAxis:
    def __init__(self, name: str, severity: Severity | None) -> None:
        self.name = name
        self._severity = severity

    def check(self, context: CheckContext) -> list[Finding]:
        if self._severity is None:
            return []
        return [Finding(check_name=self.name, severity=self._severity, reason=f"{self.name}!")]


def _multi_axis_governor(model, severity: Severity | None) -> Governor:
    modifier = PlanModifier(model)
    return Governor(model, [CostCheck(modifier), _MockAxis("geometry", severity)], modifier)


def test_affordable_plan_blocked_by_second_axis(model):
    # cost is clean, geometry blocks -> BLOCK end-to-end
    d = _multi_axis_governor(model, Severity.BLOCKING).evaluate(_load(_cases("approve")[0]))
    assert d.verdict is Verdict.BLOCK
    assert "geometry" in d.reason


def test_second_axis_warning_still_approves(model):
    d = _multi_axis_governor(model, Severity.WARNING).evaluate(_load(_cases("approve")[0]))
    assert d.verdict is Verdict.APPROVE
    assert "geometry" in d.reason  # recorded, not decisive


def test_clean_second_axis_leaves_verdict_unchanged(model):
    d = _multi_axis_governor(model, None).evaluate(_load(_cases("modify")[0]))
    assert d.verdict is Verdict.MODIFY  # cost still drives it


# --- every decision is auditable ---


def test_every_scenario_decision_round_trips(governor):
    for verdict in ("approve", "modify", "block"):
        for path in _cases(verdict):
            d = governor.evaluate(_load(path))
            assert GateDecision.model_validate_json(d.model_dump_json()) == d
