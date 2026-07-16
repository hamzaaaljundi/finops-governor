"""Randomization schema tests (M1 extension for the diversity gate)."""

import pytest
from pydantic import ValidationError

from finops_governor.schemas import (
    AssetReference,
    Budget,
    Camera,
    GenerationPlan,
    OutputModality,
    Randomization,
    RandomizationParameter,
    RenderSettings,
    Scene,
)
from finops_governor.schemas.models import Transform


def _scene(**overrides):
    base = dict(
        scene_id="s1",
        environment=AssetReference(asset_id="e", usd_path="e.usda"),
        assets=[AssetReference(asset_id="a", usd_path="a.usda")],
        cameras=[Camera(camera_id="c", transform=Transform())],
        variation_count=10,
    )
    base.update(overrides)
    return Scene(**base)


def test_parameter_valid():
    p = RandomizationParameter(name="camera.azimuth", levels=12, min_value=0, max_value=360)
    assert p.levels == 12


def test_parameter_without_range_valid():
    # discrete parameter: levels only, no min/max
    assert RandomizationParameter(name="material.type", levels=4).min_value is None


def test_parameter_bad_range_rejected():
    with pytest.raises(ValidationError):
        RandomizationParameter(name="x", levels=3, min_value=10, max_value=1)


def test_parameter_zero_levels_rejected():
    with pytest.raises(ValidationError):
        RandomizationParameter(name="x", levels=0)


def test_duplicate_parameter_names_rejected():
    with pytest.raises(ValidationError):
        Randomization(
            parameters=[
                RandomizationParameter(name="dup", levels=2),
                RandomizationParameter(name="dup", levels=3),
            ]
        )


def test_scene_randomization_is_optional():
    # backward compatibility: a scene without randomization is still valid
    assert _scene().randomization is None


def test_scene_with_randomization():
    scene = _scene(
        randomization=Randomization(parameters=[RandomizationParameter(name="light", levels=5)])
    )
    assert scene.randomization.parameters[0].levels == 5


def test_plan_with_randomization_round_trips():
    plan = GenerationPlan(
        plan_id="p",
        scenes=[
            _scene(
                randomization=Randomization(
                    parameters=[
                        RandomizationParameter(name="a", levels=3),
                        RandomizationParameter(name="b", levels=4, min_value=0, max_value=1),
                    ]
                )
            )
        ],
        modalities=[OutputModality.RGB],
        render_settings=RenderSettings(width=800, height=600),
        budget=Budget(max_usd=100),
    )
    assert GenerationPlan.model_validate_json(plan.model_dump_json()) == plan
