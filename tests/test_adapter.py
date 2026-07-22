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
    # Circular: 0 degrees == 360 degrees, so the endpoint is never duplicated (see
    # test_circular_params_never_duplicate_endpoints for the collision this prevents).
    assert "0.0" in choice_line and "330.0" in choice_line
    assert "360.0" not in choice_line


def test_circular_params_never_duplicate_endpoints():
    # Session-3 calibration bug: azimuth is a full 360-degree sweep, so 0 and 360
    # name the same physical rotation. A naive closed-interval linspace emits both,
    # silently losing one declared level's worth of true diversity - a declared
    # `levels=4` sweep became [0, 120, 240, 360], only 3 distinct rotations on disk.
    script = generate_replicator_script(_plan(parameters=[{"name": "azimuth", "levels": 4}]))
    choice_line = next(line for line in script.splitlines() if "# azimuth" in line)
    assert "360.0" not in choice_line
    assert all(v in choice_line for v in ("0.0", "90.0", "180.0", "270.0"))


def test_partial_rotation_arc_keeps_both_endpoints():
    # Only a full 360-degree declared range is circular in this sense; a partial arc
    # (e.g. a half-turn) has two genuinely different orientations at its endpoints,
    # so deduplicating them would be wrong - non-circular linspace still applies.
    script = generate_replicator_script(
        _plan(parameters=[{"name": "yaw", "levels": 4, "min_value": 0, "max_value": 180}])
    )
    choice_line = next(line for line in script.splitlines() if "# yaw" in line)
    assert "0.0" in choice_line and "180.0" in choice_line


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


def test_every_script_has_setup_light_before_trigger():
    # M9.2 postmortem: the calibration session rendered black frames because the
    # only light was emitted inside the frame trigger, where rep.create does not
    # execute - and plans without lighting variation got no light at all.
    script = generate_replicator_script(_plan(parameters=[{"name": "lighting", "levels": 4}]))
    light_at = script.index("scene_light = rep.create.light")
    trigger_at = script.index("with rep.trigger.on_frame")
    assert light_at < trigger_at


def test_light_modification_uses_the_proven_input_prims_signature():
    # Session-4 smoke postmortem: rep.modify.attribute(scene_light, 'intensity', ...)
    # (object-first) fails Replicator 1.11.35 graph build with "Invalid AttributeObj
    # in connectAttr" and renders NOTHING; the form that actually rendered session
    # 3's 600-frame coverage run is name-first with input_prims=. String tests can't
    # prove Isaac validity, but they CAN pin the empirically proven form.
    script = generate_replicator_script(_plan(parameters=[{"name": "lighting", "levels": 4}]))
    assert "rep.modify.attribute('intensity', " in script
    assert "input_prims=scene_light)" in script
    assert "rep.modify.attribute(scene_light," not in script


def test_no_creates_inside_trigger_body():
    script = generate_replicator_script(
        _plan(
            parameters=[
                {"name": "lighting", "levels": 4},
                {"name": "azimuth", "levels": 4},
            ]
        )
    )
    trigger_at = script.index("with rep.trigger.on_frame")
    writer_at = script.index("writer = rep.WriterRegistry")
    trigger_body = script[trigger_at:writer_at]
    assert "rep.create." not in trigger_body


def test_script_is_standalone_executable():
    # The M9.2 live patch, versioned: bootstrap before omni imports, completion
    # footer at the end.
    script = generate_replicator_script(_plan())
    assert script.index("SimulationApp({") < script.index("import omni.replicator")
    assert "rep.orchestrator.run_until_complete()" in script
    assert script.rstrip().endswith("simulation_app.close()")
