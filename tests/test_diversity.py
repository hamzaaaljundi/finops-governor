"""DiversityCheck tests (M4, upgraded in M6.5 Task A: expected-coverage model)."""

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.schemas import GenerationPlan
from finops_governor.validity import (
    CheckContext,
    DiversityCheck,
    Severity,
    ValidityCheck,
)
from finops_governor.validity.diversity import (
    expected_distinct,
    justified_variation_count,
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


# --- the expected-coverage math itself ---


def test_expected_distinct_converges_to_capacity():
    # heavy oversampling: expect essentially every configuration hit
    assert expected_distinct(50_000, 16) == pytest.approx(16.0, abs=1e-6)


def test_expected_distinct_models_collisions_below_capacity():
    # 90 draws over 96 cells does NOT hit 90 distinct cells (coupon-collector)
    assert expected_distinct(90, 96) == pytest.approx(58.6, abs=0.5)


# --- firing behavior ---


def test_conforms_to_interface():
    assert isinstance(DiversityCheck(), ValidityCheck)
    assert DiversityCheck().name == "diversity"


def test_well_spread_plan_is_clean(model):
    # 500 over 480 configs: expected redundancy ~38%, below the 50% default
    assert DiversityCheck().check(_context(model, 500, [12, 5, 8])) == []


def test_redundant_plan_is_modifiable(model):
    findings = DiversityCheck().check(_context(model, 5000, [12, 8]))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.MODIFIABLE  # ADR 0007: recoverable by construction
    assert f.detail["redundant_fraction"] > 0.5
    assert f.detail["expected_distinct"] == pytest.approx(96.0, abs=0.5)
    assert f.detail["justified_variation_count"] >= 1


def test_justified_count_sits_exactly_at_the_boundary():
    for capacity in (16, 96, 100, 480):
        n = justified_variation_count(capacity, waste_threshold=0.5)
        assert 1.0 - expected_distinct(n, capacity) / n <= 0.5
        assert 1.0 - expected_distinct(n + 1, capacity) / (n + 1) > 0.5


def test_justified_count_is_always_recoverable():
    # redundant_fraction(1) == 0 for every capacity -> a target always exists
    assert justified_variation_count(1) >= 1
    assert justified_variation_count(10_000) >= 1


def test_double_oversampling_now_fires(model):
    # n = 2k was invisible to the old best-case model (exactly at its cliff);
    # expected coverage shows ~57% of spend redundant -> fires at the 0.5 default
    findings = DiversityCheck().check(_context(model, 200, [10, 10]))
    assert len(findings) == 1
    assert findings[0].detail["redundant_fraction"] == pytest.approx(0.567, abs=0.01)


def test_near_capacity_waste_is_real_but_below_default(model):
    # 90 over 96: the old model reported zero waste; expected coverage says ~35%.
    # Below the 0.5 default (no finding), visible when the threshold is lowered.
    assert DiversityCheck().check(_context(model, 90, [12, 8])) == []
    findings = DiversityCheck(waste_threshold=0.2).check(_context(model, 90, [12, 8]))
    assert len(findings) == 1
    assert findings[0].detail["redundant_fraction"] == pytest.approx(0.349, abs=0.01)


def test_undeclared_randomization_is_skipped(model):
    assert DiversityCheck().check(_context(model, 100_000, [], declared=False)) == []


def test_threshold_is_tunable(model):
    ctx = _context(model, 500, [12, 5, 8])  # expected redundancy ~0.378
    assert DiversityCheck(waste_threshold=0.5).check(ctx) == []
    assert DiversityCheck(waste_threshold=0.3).check(ctx)


# --- the money metrics ---


def test_finding_quantifies_dollars_and_unit_price(model):
    findings = DiversityCheck().check(_context(model, 5000, [12, 8]))
    detail = findings[0].detail
    assert detail["estimated_wasted_usd"] > 0
    assert detail["effective_cost_per_distinct_usd"] > detail["nominal_cost_per_image_usd"]
    assert detail["capacity"] == 96.0
    assert "distinct configuration" in findings[0].reason


def test_pure_read_does_not_mutate_plan(model):
    ctx = _context(model, 5000, [12, 8])
    before = ctx.plan.model_dump()
    DiversityCheck().check(ctx)
    assert ctx.plan.model_dump() == before


# --- declaration plausibility (M8 pre-work: trust made visible) ---


def test_honest_declarations_produce_no_plausibility_warning(model):
    assert DiversityCheck().check(_context(model, 500, [12, 5, 8])) == []


def test_implausible_per_parameter_levels_warn(model):
    findings = DiversityCheck().check(_context(model, 50_000, [500, 100]))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.WARNING
    assert f.detail["kind"] == "implausible_levels"
    assert "plausibility" in f.reason


def test_capacity_oversupply_warns(model):
    # 64,000 declared configurations for 50 draws: trust doing heavy lifting
    findings = DiversityCheck().check(_context(model, 50, [40, 40, 40]))
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert findings[0].detail["kind"] == "capacity_oversupply"


def test_plausibility_and_redundancy_can_co_fire(model):
    findings = DiversityCheck().check(_context(model, 5000, [200, 1]))
    severities = {f.severity for f in findings}
    assert severities == {Severity.WARNING, Severity.MODIFIABLE}


def test_plausibility_thresholds_are_tunable(model):
    ctx = _context(model, 50_000, [500, 100])
    relaxed = DiversityCheck(plausible_max_levels=1000, plausible_capacity_factor=1e9)
    assert relaxed.check(ctx) == []


def test_plausibility_warning_never_changes_the_verdict(model):
    from finops_governor.gate import Verdict
    from finops_governor.governor import Governor

    governor = Governor.with_default_checks(model)
    decision = governor.evaluate(_context(model, 50_000, [500, 100]).plan)
    assert decision.verdict is Verdict.APPROVE  # warning recorded, never enforced
    assert "plausibility" in decision.reason
