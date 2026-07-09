"""Diversity scenario suite (M4, updated in M6.5 Task A for expected-coverage semantics).

Folder name is the expectation: efficient/ must produce NO diversity finding (including
real-but-below-threshold expected waste), redundant/ must fire with more than half the
scene's spend expected redundant. Adding a scenario is dropping a file in the right
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
    assert all(f.detail["redundant_fraction"] > 0.5 for f in findings)
    assert all(f.detail["estimated_wasted_usd"] > 0 for f in findings)
    assert all(
        f.detail["effective_cost_per_distinct_usd"]
        > f.detail["nominal_cost_per_image_usd"]
        for f in findings
    )


def test_mixed_scene_plan_flags_only_the_wasteful_scene(model):
    findings = _findings(model, SCENARIOS / "redundant" / "mixed_scenes.json")
    assert len(findings) == 1
    assert "wasteful" in findings[0].reason


def test_redundant_scenarios_get_value_trimmed_not_blocked(model):
    from finops_governor.gate import Verdict

    governor = Governor.with_default_checks(model)
    plan = GenerationPlan.model_validate(
        json.loads((SCENARIOS / "redundant" / "production_scale.json").read_text())
    )
    decision = governor.evaluate(plan)
    assert decision.verdict is Verdict.MODIFY  # ADR 0007: act on the waste
    assert "diversity" in decision.reason
    assert decision.modified_estimate.total_usd < decision.estimate.total_usd
