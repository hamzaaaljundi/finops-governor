"""v2.0-energy tests: the chain, the curves, the advice, the reclass rule, and
the headline (trim-carbon accounting)."""

import json
from pathlib import Path

import pytest

from finops_governor.energy import (
    DEFAULT_PUE,
    StaticIntensityCurves,
    estimate_energy,
    schedule_advice,
    trim_carbon_avoided,
)
from finops_governor.estimator import GpuRenderCostModel, load_profiles
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def profile():
    return load_profiles()["a10g"]


@pytest.fixture(scope="module")
def governor(profile):
    # fixed hour -> deterministic decisions in tests (19:00 = evening peak)
    return Governor.with_default_checks(GpuRenderCostModel(profile))


def _gov(profile, hour):
    return Governor(
        cost_model=GpuRenderCostModel(profile),
        checks=Governor.with_default_checks(GpuRenderCostModel(profile))._checks,
        energy_hour=hour,
    )


def _plan(name="plans/valid/minimal.json", **overrides):
    data = json.loads((FIXTURES / name).read_text())
    data.update(overrides)
    return GenerationPlan.model_validate(data)


# --- the chain ---------------------------------------------------------------


def test_energy_chain_is_the_documented_formula(profile):
    cost = GpuRenderCostModel(profile).estimate(_plan())
    src = StaticIntensityCurves()
    e = estimate_energy(cost, profile, src, "us-east-1", hour=19)
    expected_kwh = profile.tdp_kw * profile.default_utilization * cost.total_gpu_hours * DEFAULT_PUE
    assert e.estimated_kwh == pytest.approx(expected_kwh, abs=1e-6)
    assert e.estimated_gco2 == pytest.approx(
        expected_kwh * src.intensity_at("us-east-1", 19), abs=1e-3
    )


def test_profiles_carry_real_tdp_values(profile):
    # A10G is a 150 W part; T4 70 W; H100 PCIe 350 W (the variant the price row
    # prices). Guard against the config drifting to made-up numbers.
    profiles = load_profiles()
    assert profiles["a10g"].tdp_kw == pytest.approx(0.150)
    assert profiles["t4"].tdp_kw == pytest.approx(0.070)
    assert profiles["h100"].tdp_kw == pytest.approx(0.350)


def test_unknown_region_raises():
    with pytest.raises(KeyError, match="unknown region"):
        StaticIntensityCurves().intensity_at("mars-north-1", 3)


# --- advice per urgency ------------------------------------------------------


def test_interactive_is_never_advised_to_wait(profile):
    cost = GpuRenderCostModel(profile).estimate(_plan())
    src = StaticIntensityCurves()
    e = estimate_energy(cost, profile, src, "us-east-1", hour=19)  # peak
    adv = schedule_advice(e, "interactive", src)
    assert adv.recommended_start_hour == 19
    assert adv.projected_gco2_saved == 0.0
    assert "never deferred" in adv.reason


def test_deferrable_moves_to_the_lowest_window(profile):
    cost = GpuRenderCostModel(profile).estimate(_plan())
    src = StaticIntensityCurves()
    e = estimate_energy(cost, profile, src, "us-east-1", hour=19)
    adv = schedule_advice(e, "deferrable", src)
    assert adv.recommended_intensity == min(src.intensity_at("us-east-1", h) for h in range(24))
    assert adv.projected_gco2_saved > 0


def test_standard_defers_only_above_threshold(profile):
    cost = GpuRenderCostModel(profile).estimate(_plan())
    src = StaticIntensityCurves()
    peak = estimate_energy(cost, profile, src, "us-east-1", hour=19)  # 460 > 400
    assert schedule_advice(peak, "standard", src).projected_gco2_saved > 0
    low = estimate_energy(cost, profile, src, "us-west-2", hour=19)  # hydro region
    adv = schedule_advice(low, "standard", src)
    assert adv.recommended_start_hour == 19 and adv.projected_gco2_saved == 0.0


# --- the reclass governance rule --------------------------------------------


def test_unapproved_deferrable_to_interactive_reclass_blocks(governor):
    d = governor.evaluate(_plan(urgency="interactive", urgency_reclassified_from="deferrable"))
    assert d.verdict.value == "BLOCK"
    assert "energy_policy" in d.reason and "human approval" in d.reason


def test_approved_reclass_passes(governor):
    d = governor.evaluate(
        _plan(
            urgency="interactive",
            urgency_reclassified_from="deferrable",
            approved_reclass=True,
        )
    )
    assert d.verdict.value == "APPROVE"


def test_plain_interactive_needs_no_approval(governor):
    assert governor.evaluate(_plan(urgency="interactive")).verdict.value == "APPROVE"


# --- the headline: trim-carbon accounting ------------------------------------


def test_modify_carries_gco2_avoided_by_trim(governor):
    red = json.loads((FIXTURES / "diversity" / "redundant" / "production_scale.json").read_text())
    d = governor.evaluate(GenerationPlan.model_validate(red))
    assert d.verdict.value == "MODIFY"
    assert d.gco2_avoided_by_trim is not None and d.gco2_avoided_by_trim > 0
    assert d.kwh_avoided_by_trim is not None and d.kwh_avoided_by_trim > 0
    # accounting identity: avoided = original - modified, on the same hour/region
    assert d.gco2_avoided_by_trim == pytest.approx(
        d.energy.estimated_gco2 - d.modified_energy.estimated_gco2, abs=1e-3
    )


def test_trim_carbon_never_negative(profile):
    cost = GpuRenderCostModel(profile).estimate(_plan())
    src = StaticIntensityCurves()
    e = estimate_energy(cost, profile, src, "us-east-1", 12)
    kwh, g = trim_carbon_avoided(e, e)
    assert kwh == 0.0 and g == 0.0


# --- decisions always carry the energy block ---------------------------------


def test_every_decision_carries_energy_and_advice(governor):
    d = governor.evaluate(_plan())
    assert d.energy is not None and d.energy.estimated_kwh > 0
    assert d.schedule is not None
    assert 0 <= d.energy.hour_at_decision <= 23


def test_pre_v2_plan_fixtures_still_validate_with_defaults():
    p = _plan()  # no urgency in the fixture file
    assert p.urgency == "standard" and p.approved_reclass is False
