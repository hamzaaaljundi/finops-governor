"""Plan-to-Replicator adapter tests (M9, Task 9.4).

All on-Mac: the emitted script is compiled and content-asserted; only RUNNING it needs
Isaac Sim on an RTX GPU (that run is the calibration session, docs/calibration.md).
"""

import pytest

from finops_governor.adapter import AdapterError, generate_replicator_script
from finops_governor.cli import main
from finops_governor.schemas import GenerationPlan


def _plan(
    variation_count: int = 120,
    parameters: list[dict] | None = None,
    modalities: tuple[str, ...] = ("RGB", "DEPTH"),
    renderer: str = "PATH_TRACED",
    spp: int = 128,
    scenes: int = 1,
) -> GenerationPlan:
    scene = {
        "scene_id": "cal",
        "environment": {"asset_id": "floor", "usd_path": "assets/floor.usda"},
        "assets": [
            {"asset_id": "arm", "usd_path": "assets/arm.usda"},
            {"asset_id": "box", "usd_path": "assets/box.usda"},
        ],
        "cameras": [{"camera_id": "cam", "transform": {"translation": [0, 1, 5]}}],
        "variation_count": variation_count,
    }
    if parameters is not None:
        scene["randomization"] = {"parameters": parameters}
    return GenerationPlan.model_validate(
        {
            "plan_id": "p",
            "scenes": [dict(scene, scene_id=f"cal{i}") for i in range(scenes)],
            "modalities": list(modalities),
            "render_settings": {
                "width": 1920,
                "height": 1080,
                "samples_per_pixel": spp,
                "renderer": renderer,
            },
            "budget": {"max_usd": 50},
        }
    )


def test_emitted_script_is_valid_python():
    script = generate_replicator_script(_plan(parameters=[{"name": "azimuth", "levels": 12}]))
    compile(script, "generated_replicator.py", "exec")  # raises on invalid syntax


def test_variation_count_drives_num_frames():
    script = generate_replicator_script(_plan(variation_count=77))
    assert "num_frames=77" in script


def test_render_settings_are_embedded():
    script = generate_replicator_script(_plan())
    assert "(1920, 1080)" in script
    assert "set_render_pathtraced(samples_per_pixel=128)" in script


def test_rasterized_maps_to_realtime():
    script = generate_replicator_script(_plan(renderer="RASTERIZED", spp=1))
    assert "set_render_rtx_realtime()" in script
    assert "pathtraced" not in script


def test_modalities_map_to_writer_flags_and_pose_is_warned():
    script = generate_replicator_script(_plan(modalities=("RGB", "DEPTH", "POSE")))
    assert "rgb=True" in script
    assert "distance_to_camera=True" in script
    assert "WARNING: modality POSE" in script


def test_declared_levels_are_honored_exactly():
    script = generate_replicator_script(_plan(parameters=[{"name": "azimuth", "levels": 12}]))
    choice_line = next(line for line in script.splitlines() if "# azimuth" in line)
    assert choice_line.count(",") >= 11  # 12 values in the choice list
    assert "0.0" in choice_line and "360.0" in choice_line


def test_declared_range_is_honored():
    script = generate_replicator_script(
        _plan(parameters=[{"name": "lighting", "levels": 5, "min_value": 500, "max_value": 2500}])
    )
    light_line = next(line for line in script.splitlines() if "# lighting" in line)
    assert "500.0" in light_line and "2500.0" in light_line


def test_unknown_parameter_is_skipped_with_a_trust_warning():
    script = generate_replicator_script(_plan(parameters=[{"name": "quantum_flux", "levels": 99}]))
    assert "WARNING: parameter 'quantum_flux'" in script
    assert "trusted this declaration" in script


def test_no_randomization_still_compiles():
    script = generate_replicator_script(_plan())
    compile(script, "g.py", "exec")
    assert "no randomization declared" in script


def test_multi_scene_raises_adapter_error():
    with pytest.raises(AdapterError, match="single-scene"):
        generate_replicator_script(_plan(scenes=2))


def test_camera_transform_is_embedded():
    script = generate_replicator_script(_plan())
    assert "position=(0.0, 1.0, 5.0)" in script


# --- the CLI flag ---


def test_cli_emits_the_script(capsys, tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(_plan().model_dump_json())
    out_file = tmp_path / "scene.py"
    code = main([str(plan_file), "--emit-replicator", str(out_file)])
    out = capsys.readouterr().out
    assert code == 0
    assert f"replicator: {out_file}" in out
    compile(out_file.read_text(), "cli_generated.py", "exec")


def test_cli_emit_requires_evaluate_mode(capsys):
    code = main(["some request", "--budget", "50", "--emit-replicator", "x.py"])
    err = capsys.readouterr().err
    assert code == 3
    assert "requires evaluate mode" in err
