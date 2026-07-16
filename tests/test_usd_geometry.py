"""UsdGeometryCheck tests (M5, Task 5.4).

Grades the geometry axis against the hand-authored USD fixtures: each defect fixture
must produce exactly its intended finding (right severity, right subject), the clean
fixture must produce none, and plan-side defects (missing stage, missing asset, camera
aimed away) must pair correctly with valid stages.
"""

from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.schemas import GenerationPlan
from finops_governor.validity import CheckContext, Severity, ValidityCheck
from finops_governor.validity.usd_geometry import UsdGeometryCheck
from finops_governor.validity.usd_stage import UsdStageLoader

USD_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "usd"


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


def _plan(
    stage: str,
    cam_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    assets: tuple[str, ...] = ("arm", "box"),
    scenes: list[dict] | None = None,
) -> GenerationPlan:
    if scenes is None:
        scenes = [
            {
                "scene_id": "s1",
                "environment": {
                    "asset_id": "floor",
                    "usd_path": str(USD_FIXTURES / stage),
                },
                "assets": [{"asset_id": a, "usd_path": str(USD_FIXTURES / stage)} for a in assets],
                "cameras": [
                    {
                        "camera_id": "cam",
                        "transform": {
                            "translation": [0.0, 1.0, 5.0],
                            "rotation": list(cam_rotation),
                        },
                    }
                ],
                "variation_count": 10,
            }
        ]
    return GenerationPlan.model_validate(
        {
            "plan_id": "p",
            "scenes": scenes,
            "modalities": ["RGB"],
            "render_settings": {"width": 1280, "height": 720},
            "budget": {"max_usd": 100},
        }
    )


def _findings(model, plan, **check_kwargs):
    ctx = CheckContext(plan=plan, cost_estimate=model.estimate(plan))
    return UsdGeometryCheck(**check_kwargs).check(ctx)


def test_conforms_to_interface():
    check = UsdGeometryCheck()
    assert isinstance(check, ValidityCheck)
    assert check.name == "usd_geometry"


def test_valid_scene_is_clean(model):
    assert _findings(model, _plan("valid.usda")) == []


def test_floor_clip_blocks_with_penetration_detail(model):
    findings = _findings(model, _plan("floor_clip.usda"))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.BLOCKING
    assert f.detail["asset_id"] == "arm"
    assert f.detail["penetration_m"] == pytest.approx(0.1, abs=1e-3)


def test_asset_overlap_warns_not_blocks(model):
    findings = _findings(model, _plan("asset_overlap.usda"))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.WARNING
    assert {f.detail["asset_a"], f.detail["asset_b"]} == {"arm", "box"}


def test_missing_stage_blocks(model):
    findings = _findings(model, _plan("does_not_exist.usda"))
    assert len(findings) == 1
    assert findings[0].severity is Severity.BLOCKING
    assert "cannot be opened" in findings[0].reason or "does not resolve" in findings[0].reason


def test_missing_asset_blocks_but_others_still_checked(model):
    findings = _findings(model, _plan("valid.usda", assets=("arm", "box", "gripper")))
    assert len(findings) == 1  # only the missing asset; arm/box geometry stays clean
    f = findings[0]
    assert f.severity is Severity.BLOCKING
    assert f.detail["asset_id"] == "gripper"


def test_camera_aimed_away_warns(model):
    findings = _findings(model, _plan("valid.usda", cam_rotation=(0.0, 180.0, 0.0)))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.WARNING
    assert f.detail["camera_id"] == "cam"
    assert f.detail["dot"] <= 0


def test_epsilon_is_tunable(model):
    # with a tolerance larger than the 0.1 m defect, floor_clip stops firing
    assert _findings(model, _plan("floor_clip.usda"), penetration_epsilon_m=0.5) == []


def test_multi_scene_flags_only_the_broken_scene(model):
    def scene(sid, stage):
        return {
            "scene_id": sid,
            "environment": {
                "asset_id": "floor",
                "usd_path": str(USD_FIXTURES / stage),
            },
            "assets": [
                {"asset_id": a, "usd_path": str(USD_FIXTURES / stage)} for a in ("arm", "box")
            ],
            "cameras": [
                {
                    "camera_id": f"{sid}-cam",
                    "transform": {"translation": [0.0, 1.0, 5.0]},
                }
            ],
            "variation_count": 10,
        }

    plan = _plan("", scenes=[scene("good", "valid.usda"), scene("bad", "floor_clip.usda")])
    findings = _findings(model, plan)
    assert len(findings) == 1
    assert findings[0].detail["scene_id"] == "bad"


def test_stage_loading_is_memoized(model):
    loader = UsdStageLoader()
    plan = _plan("valid.usda")  # env + 2 assets all reference the same stage path
    ctx = CheckContext(plan=plan, cost_estimate=model.estimate(plan))
    UsdGeometryCheck(loader=loader).check(ctx)
    assert len(loader._cache) == 1  # one path -> opened exactly once


def test_pure_read_does_not_mutate_plan(model):
    plan = _plan("floor_clip.usda")
    before = plan.model_dump()
    _findings(model, plan)
    assert plan.model_dump() == before
