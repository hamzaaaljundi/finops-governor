"""Cost estimator tests (M2, Task 2.3).

Verifies the GpuRenderCostModel against the numbers specified in docs/cost-model.md,
plus the structural properties the gate will rely on: interface conformance, per-scene
breakdown integrity, multi-device parameterization, and determinism.
"""

import json
from pathlib import Path

import pytest

from finops_governor.estimator import (
    CostModel,
    GpuRenderCostModel,
    get_profile,
)
from finops_governor.schemas import GenerationPlan
from finops_governor.schemas.models import (
    AssetReference,
    Budget,
    Camera,
    OutputModality,
    RenderSettings,
    RendererType,
    Scene,
    Transform,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plans" / "valid"


def _load(name: str) -> GenerationPlan:
    return GenerationPlan.model_validate(json.loads((FIXTURES / name).read_text()))


def _model(profile_id: str = "a10g") -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile(profile_id))


def _scene(scene_id: str, variations: int, cameras: int) -> Scene:
    return Scene(
        scene_id=scene_id,
        environment=AssetReference(asset_id=f"{scene_id}-env", usd_path="e.usda"),
        assets=[AssetReference(asset_id=f"{scene_id}-a", usd_path="a.usda")],
        cameras=[
            Camera(camera_id=f"{scene_id}-c{i}", transform=Transform()) for i in range(cameras)
        ],
        variation_count=variations,
    )


def _plan(scenes, modalities, width=1920, height=1080, spp=128, renderer=None) -> GenerationPlan:
    rs = (
        RenderSettings(width=width, height=height, samples_per_pixel=spp, renderer=renderer)
        if renderer
        else RenderSettings(width=width, height=height, samples_per_pixel=spp)
    )
    return GenerationPlan(
        plan_id="test",
        scenes=scenes,
        modalities=modalities,
        render_settings=rs,
        budget=Budget(max_usd=1_000_000),
    )


def test_conforms_to_cost_model_interface():
    assert isinstance(_model(), CostModel)


def test_minimal_matches_spec():
    # docs/cost-model.md §6.1: ~$0.013 on A10G (session-3 constants, ADR 0009)
    est = _model().estimate(_load("minimal.json"))
    assert est.total_images == 1
    assert est.total_usd == pytest.approx(0.0126, rel=0.02)


def test_per_scene_subtotals_sum_to_total():
    est = _model().estimate(_load("multi_scene.json"))
    assert sum(s.subtotal_usd for s in est.per_scene) == pytest.approx(est.total_usd)


def test_same_plan_costs_differ_across_devices():
    plan = _load("multi_scene.json")
    costs = {
        pid: GpuRenderCostModel(get_profile(pid)).estimate(plan).total_usd
        for pid in ("t4", "a10g", "h100")
    }
    # all three differ, and the A10G is cheapest for this workload (§6.3)
    assert len(set(round(c, 4) for c in costs.values())) == 3
    assert min(costs, key=costs.get) == "a10g"


def test_estimate_is_deterministic():
    plan = _load("multi_scene.json")
    m = _model()
    assert m.estimate(plan).model_dump() == m.estimate(plan).model_dump()


def test_affine_fixed_overhead_is_charged():
    # A single tiny image still incurs the per-scene ingestion overhead, so cost is
    # dominated by fixed cost, not the (near-zero) render time.
    est = _model().estimate(
        _plan([_scene("s", 1, 1)], [OutputModality.RGB], width=64, height=64, spp=1)
    )
    assert est.per_scene[0].fixed_seconds == get_profile("a10g").fixed_ingestion_seconds
    assert est.total_usd > 0


def test_more_modalities_costs_more():
    scenes = [_scene("s", 100, 1)]
    rgb = _model().estimate(_plan(scenes, [OutputModality.RGB])).total_usd
    rgb_plus = (
        _model().estimate(_plan(scenes, [OutputModality.RGB, OutputModality.DEPTH])).total_usd
    )
    assert rgb_plus > rgb


def test_rasterized_cheaper_than_path_traced():
    scenes = [_scene("s", 100, 1)]
    pt = _model().estimate(_plan(scenes, [OutputModality.RGB], spp=128)).total_usd
    rz = (
        _model()
        .estimate(_plan(scenes, [OutputModality.RGB], spp=1, renderer=RendererType.RASTERIZED))
        .total_usd
    )
    assert rz < pt


def test_annotation_modalities_charge_ingestion_extra():
    # ADR 0009: annotation-tier modalities cost per-scene ingestion, not per-frame
    p = get_profile("a10g")
    scenes = [_scene("s", 100, 1)]
    without = _model().estimate(_plan(scenes, [OutputModality.RGB]))
    with_annot = _model().estimate(
        _plan(scenes, [OutputModality.RGB, OutputModality.SEMANTIC_SEGMENTATION])
    )
    assert with_annot.per_scene[0].fixed_seconds == pytest.approx(
        p.fixed_ingestion_seconds + p.annot_ingestion_extra_seconds
    )
    assert without.per_scene[0].fixed_seconds == pytest.approx(p.fixed_ingestion_seconds)
    # the fixed delta is exact; the tiny modality-weight delta rides on render_s
    fixed_delta_usd = (
        p.annot_ingestion_extra_seconds * p.contingency_factor / 3600 * p.price_per_hour_usd
    )
    assert with_annot.total_usd - without.total_usd > fixed_delta_usd * 0.99


def test_annot_extra_is_charged_per_scene():
    p = get_profile("a10g")
    est = _model().estimate(
        _plan(
            [_scene("s1", 10, 1), _scene("s2", 10, 1)],
            [OutputModality.RGB, OutputModality.BBOX_2D],
        )
    )
    for sc in est.per_scene:
        assert sc.fixed_seconds == pytest.approx(
            p.fixed_ingestion_seconds + p.annot_ingestion_extra_seconds
        )


def test_unmeasured_profiles_default_annot_extra_to_zero():
    for pid in ("t4", "h100"):
        p = get_profile(pid)
        assert p.annot_ingestion_extra_seconds == 0.0
        est = GpuRenderCostModel(p).estimate(
            _plan([_scene("s", 10, 1)], [OutputModality.RGB, OutputModality.BBOX_2D])
        )
        assert est.per_scene[0].fixed_seconds == p.fixed_ingestion_seconds
