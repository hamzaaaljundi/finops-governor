"""Schema validation tests (M1, Task 1.7).

Loads every fixture under fixtures/plans/ and asserts the contract holds: valid
plans parse, invalid plans are rejected. Fixtures are auto-discovered, so adding a
new fixture file adds a test case with no change to this file.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from finops_governor.schemas import (
    AssetReference,
    Budget,
    Camera,
    GenerationPlan,
    OutputModality,
    RenderSettings,
    Scene,
    Transform,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plans"
VALID_DIR = FIXTURES / "valid"
INVALID_DIR = FIXTURES / "invalid"
VALID = sorted(VALID_DIR.glob("*.json"))
INVALID = sorted(INVALID_DIR.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_fixtures_are_discovered():
    # Guard: if the paths are wrong, the parametrized tests would silently pass
    # with zero cases. This makes that failure loud.
    assert VALID, f"no valid fixtures found under {VALID_DIR}"
    assert INVALID, f"no invalid fixtures found under {INVALID_DIR}"


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_valid_fixtures_parse(path: Path):
    plan = GenerationPlan.model_validate(_load(path))
    assert isinstance(plan, GenerationPlan)


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.name)
def test_invalid_fixtures_are_rejected(path: Path):
    with pytest.raises(ValidationError):
        GenerationPlan.model_validate(_load(path))


# Assert not just THAT an invalid fixture fails, but that it fails for the RIGHT
# reason — so a fixture accidentally invalid for some other cause is caught.
@pytest.mark.parametrize(
    "filename, expected_substring",
    [
        ("bad_usd_extension.json", "usd_path must end"),
        ("negative_scale.json", "scale components must be strictly greater"),
        ("rasterized_high_samples.json", "RASTERIZED renderer does not use"),
        ("duplicate_asset_ids.json", "Duplicate asset_id"),
        ("duplicate_camera_ids.json", "Duplicate camera_id"),
        ("duplicate_scene_ids.json", "scene_id in the plan must be unique"),
        ("duplicate_modalities.json", "modalities cannot contain duplicates"),
        ("unknown_field.json", "Extra inputs are not permitted"),
        ("empty_assets.json", "at least 1 item"),
        ("variation_count_zero.json", "greater than or equal to 1"),
        ("out_of_range_dimensions.json", "less than or equal to 8192"),
        ("missing_required_field.json", "Field required"),
        ("randomization_bad_range.json", "min_value must be less than max_value"),
        ("randomization_dup_params.json", "parameter names must be unique"),
        ("randomization_zero_levels.json", "greater than or equal to 1"),
    ],
)
def test_invalid_fixture_reports_expected_rule(filename: str, expected_substring: str):
    with pytest.raises(ValidationError) as exc_info:
        GenerationPlan.model_validate(_load(INVALID_DIR / filename))
    messages = " | ".join(e["msg"] for e in exc_info.value.errors())
    assert expected_substring in messages, (
        f"{filename} raised, but not for the expected rule.\nGot: {messages}"
    )


def test_plan_constructs_programmatically():
    plan = GenerationPlan(
        plan_id="p1",
        scenes=[
            Scene(
                scene_id="s1",
                environment=AssetReference(asset_id="floor", usd_path="floor.usda"),
                assets=[AssetReference(asset_id="arm", usd_path="arm.usda")],
                cameras=[Camera(camera_id="c1", transform=Transform())],
                variation_count=10,
            )
        ],
        modalities=[OutputModality.RGB, OutputModality.DEPTH],
        render_settings=RenderSettings(width=1920, height=1080),
        budget=Budget(max_usd=500),
    )
    assert plan.created_at.tzinfo is not None  # timezone-aware


def test_json_round_trip_is_lossless():
    plan = GenerationPlan.model_validate(_load(VALID_DIR / "multi_scene.json"))
    reloaded = GenerationPlan.model_validate_json(plan.model_dump_json())
    assert reloaded == plan
