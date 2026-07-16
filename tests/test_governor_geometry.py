"""Governor + geometry integration tests (M5, Task 5.5).

Proves the three-axis composition end-to-end with a REAL blocking axis (not the M3
mocks): geometry BLOCKING dominates cost and diversity; geometry warnings are recorded
without changing the verdict; and the plan-level default wiring stays geometry-free.
"""

import json
from pathlib import Path

import pytest

from finops_governor.cli import main
from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate import Verdict
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan

REPO = Path(__file__).resolve().parents[1]
USD = REPO / "fixtures" / "usd"
SCENARIOS = REPO / "fixtures" / "geometry"


@pytest.fixture(scope="module")
def model() -> GpuRenderCostModel:
    return GpuRenderCostModel(get_profile("a10g"))


def _plan(
    stage: str,
    budget: float = 100.0,
    cam_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    randomization: dict | None = None,
    variation_count: int = 50,
) -> GenerationPlan:
    scene = {
        "scene_id": "station",
        "environment": {"asset_id": "floor", "usd_path": str(USD / stage)},
        "assets": [{"asset_id": a, "usd_path": str(USD / stage)} for a in ("arm", "box")],
        "cameras": [
            {
                "camera_id": "cam",
                "transform": {
                    "translation": [0.0, 1.0, 5.0],
                    "rotation": list(cam_rotation),
                },
            }
        ],
        "variation_count": variation_count,
    }
    if randomization is not None:
        scene["randomization"] = randomization
    return GenerationPlan.model_validate(
        {
            "plan_id": "p",
            "scenes": [scene],
            "modalities": ["RGB", "DEPTH"],
            "render_settings": {"width": 1280, "height": 720},
            "budget": {"max_usd": budget},
        }
    )


def _load_scenario(name: str) -> GenerationPlan:
    data = json.loads((SCENARIOS / name).read_text())
    for scene in data["scenes"]:
        scene["environment"]["usd_path"] = str(REPO / scene["environment"]["usd_path"])
        for asset in scene["assets"]:
            asset["usd_path"] = str(REPO / asset["usd_path"])
    return GenerationPlan.model_validate(data)


# --- three-axis composition with a real blocking axis ---


def test_affordable_diverse_but_broken_geometry_blocks(model):
    decision = Governor.with_all_checks(model).evaluate(_plan("floor_clip.usda"))
    assert decision.verdict is Verdict.BLOCK
    assert "usd_geometry" in decision.reason


def test_geometry_blocking_dominates_cost_modify(model):
    # budget forces cost into MODIFY territory; geometry must still BLOCK,
    # and BOTH findings must appear in the audit reason (ADR 0005).
    plan = _plan("floor_clip.usda", budget=0.005)
    decision = Governor.with_all_checks(model).evaluate(plan)
    assert decision.verdict is Verdict.BLOCK
    assert "usd_geometry" in decision.reason
    assert "cost_budget" in decision.reason


def test_clean_geometry_with_redundancy_gets_value_trimmed(model):
    plan = _plan(
        "valid.usda",
        variation_count=5000,
        randomization={"parameters": [{"name": "az", "levels": 4}]},
    )
    decision = Governor.with_all_checks(model).evaluate(plan)
    assert decision.verdict is Verdict.MODIFY  # ADR 0007
    assert "diversity" in decision.reason
    assert "usd_geometry" not in decision.reason  # geometry stays silent when clean
    assert any(m.startswith("value:") for m in decision.modifications)


def test_camera_away_approves_with_geometry_warning(model):
    decision = Governor.with_all_checks(model).evaluate(
        _plan("valid.usda", cam_rotation=(0.0, 180.0, 0.0))
    )
    assert decision.verdict is Verdict.APPROVE
    assert "usd_geometry" in decision.reason
    assert "oriented away" in decision.reason


def test_default_wiring_stays_geometry_free(model):
    # regression guard: plans with placeholder paths must still work on the default
    # (plan-level) wiring - geometry is explicit opt-in.
    plan = GenerationPlan.model_validate(
        {
            "plan_id": "p",
            "scenes": [
                {
                    "scene_id": "s",
                    "environment": {"asset_id": "e", "usd_path": "e.usda"},
                    "assets": [{"asset_id": "a", "usd_path": "a.usda"}],
                    "cameras": [{"camera_id": "c", "transform": {}}],
                    "variation_count": 10,
                }
            ],
            "modalities": ["RGB"],
            "render_settings": {"width": 1280, "height": 720},
            "budget": {"max_usd": 100},
        }
    )
    decision = Governor.with_default_checks(model).evaluate(plan)
    assert decision.verdict is Verdict.APPROVE


# --- scenario fixtures drive to the expected verdicts ---


@pytest.mark.parametrize(
    "fixture, expected_verdict, must_mention",
    [
        ("clean_scene.json", Verdict.APPROVE, None),
        ("floor_clip_scene.json", Verdict.BLOCK, "penetrates"),
        ("camera_away_scene.json", Verdict.APPROVE, "oriented away"),
    ],
)
def test_geometry_scenarios(model, fixture, expected_verdict, must_mention):
    decision = Governor.with_all_checks(model).evaluate(_load_scenario(fixture))
    assert decision.verdict is expected_verdict
    if must_mention:
        assert must_mention in decision.reason


# --- the CLI flag, end to end ---


def test_cli_geometry_flag_blocks_broken_scene(model, capsys, monkeypatch):
    monkeypatch.chdir(REPO)  # scenario fixtures use repo-root-relative stage paths
    code = main(["fixtures/geometry/floor_clip_scene.json", "--geometry"])
    out = capsys.readouterr().out
    assert code == 2
    assert "verdict:   BLOCK" in out
    assert "penetrates" in out
