"""DiversityCheck tests (M4, Task 4.2)."""

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.schemas import GenerationPlan
from finops_governor.validity import (
    CheckContext,
    DiversityCheck,
    Severity,
    ValidityCheck,
)


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


def _context(model, variation_count: int, levels: list[int], declared: bool = True):
    scene = {
        "scene_id": "s",
        "environment": {"asset_id": "e", "usd_path": "e.usda"},
        "assets": [{"asset_id": "a", "usd_path": "a.usda"}],
        "cameras": [{"camera_id": "c", "transform": {}}],
        "variation_count": variation_count,
    }
    if declared:
        scene["randomization"] = {
            "parameters": [{"name": f"p{i}", "levels": v} for i, v in enumerate(levels)]
        }
    plan = GenerationPlan.model_validate(
        {
            "plan_id": "p",
            "scenes": [scene],
            "modalities": ["RGB", "DEPTH"],
            "render_settings": {"width": 1920, "height": 1080},
            "budget": {"max_usd": 1_000_000},
        }
    )
    return CheckContext(plan=plan, cost_estimate=model.estimate(plan))


def test_conforms_to_interface():
    assert isinstance(DiversityCheck(), ValidityCheck)
    assert DiversityCheck().name == "diversity"


def test_well_spread_plan_is_clean(model):
    # 500 variations across 12*5*8 = 480 configs -> ratio 1.04 -> below threshold
    assert DiversityCheck().check(_context(model, 500, [12, 5, 8])) == []


def test_redundant_plan_warns(model):
    # 5000 variations across 12*8 = 96 configs -> ratio ~52 -> warning
    findings = DiversityCheck().check(_context(model, 5000, [12, 8]))
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].detail["redundancy_ratio"] > 2.0


def test_undeclared_randomization_is_skipped(model):
    # no randomization declared -> nothing to judge -> no finding, even at huge counts
    assert DiversityCheck().check(_context(model, 100_000, [], declared=False)) == []


def test_finding_quantifies_wasted_dollars(model):
    findings = DiversityCheck().check(_context(model, 5000, [12, 8]))
    detail = findings[0].detail
    assert detail["estimated_wasted_usd"] > 0
    assert 0 < detail["redundant_fraction"] < 1
    assert detail["capacity"] == 96.0


def test_threshold_is_tunable(model):
    ctx = _context(model, 500, [12, 5, 8])  # ratio 1.04
    assert DiversityCheck(redundancy_threshold=2.0).check(ctx) == []  # not flagged
    assert DiversityCheck(redundancy_threshold=1.0).check(ctx)  # flagged at lower bar


def test_exactly_at_threshold_is_clean(model):
    # ratio exactly == threshold must NOT fire (strictly greater triggers)
    ctx = _context(model, 200, [10, 10])  # 200 / 100 = 2.0
    assert DiversityCheck(redundancy_threshold=2.0).check(ctx) == []


def test_pure_read_does_not_mutate_plan(model):
    ctx = _context(model, 5000, [12, 8])
    before = ctx.plan.model_dump()
    DiversityCheck().check(ctx)
    assert ctx.plan.model_dump() == before
