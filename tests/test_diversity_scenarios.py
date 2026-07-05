"""Diversity scenario suite (M4, Task 4.4).

Drives named diversity fixtures through the DiversityCheck and the composed Governor.
The folder name is the expectation: efficient/ must produce NO diversity finding,
redundant/ must produce at least one. Adding a scenario is dropping a file in the right
folder - no test change.
"""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan
from finops_governor.validity import CheckContext, DiversityCheck

SCENARIOS = Path(__file__).resolve().parents[1] / "fixtures" / "diversity"


def _cases(kind: str) -> list[Path]:
    return sorted((SCENARIOS / kind).glob("*.json"))


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


def _findings(model, path: Path):
    plan = GenerationPlan.model_validate(json.loads(path.read_text()))
    ctx = CheckContext(plan=plan, cost_estimate=model.estimate(plan))
    return DiversityCheck().check(ctx)


def test_scenarios_discovered():
    assert _cases("efficient") and _cases("redundant")


@pytest.mark.parametrize("path", _cases("efficient"), ids=_id)
def test_efficient_scenarios_produce_no_finding(model, path):
    assert _findings(model, path) == []


@pytest.mark.parametrize("path", _cases("redundant"), ids=_id)
def test_redundant_scenarios_warn_with_dollar_waste(model, path):
    findings = _findings(model, path)
    assert findings, f"{path.name} should have flagged redundancy"
    assert all(f.detail["estimated_wasted_usd"] > 0 for f in findings)
    assert all(f.detail["redundancy_ratio"] > 2.0 for f in findings)


def test_mixed_scene_plan_flags_only_the_wasteful_scene(model):
    findings = _findings(model, SCENARIOS / "redundant" / "mixed_scenes.json")
    assert len(findings) == 1  # only the wasteful scene, not the efficient one
    assert "wasteful" in findings[0].reason


def test_redundant_scenarios_do_not_block_through_governor(model):
    # diversity is a WARNING: even a heavily-redundant, affordable plan approves
    governor = Governor.with_default_checks(model)
    plan = GenerationPlan.model_validate(
        json.loads((SCENARIOS / "redundant" / "production_scale.json").read_text())
    )
    decision = governor.evaluate(plan)
    assert "diversity" in decision.reason  # recorded end-to-end
