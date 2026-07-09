"""CLI plan-mode tests (M6, Task 6.5).

Drives the NL -> plan -> Governor flow through main() with an injected fake model:
no network, no keys, every path in CI.
"""

import json


from finops_governor.cli import main
from finops_governor.planner import FakePlannerModel
from finops_governor.schemas import GenerationPlan


def _plan_json(budget: float = 999.0, variation_count: int = 500) -> str:
    return json.dumps(
        {
            "plan_id": "arm-500",
            "scenes": [
                {
                    "scene_id": "assembly",
                    "environment": {"asset_id": "floor", "usd_path": "floor.usda"},
                    "assets": [{"asset_id": "arm", "usd_path": "arm.usda"}],
                    "cameras": [{"camera_id": "cam", "transform": {}}],
                    "variation_count": variation_count,
                    "randomization": {
                        "parameters": [
                            {"name": "azimuth", "levels": 12},
                            {"name": "light", "levels": 5},
                            {"name": "pose", "levels": 8},
                        ]
                    },
                }
            ],
            "modalities": ["RGB", "DEPTH"],
            "render_settings": {"width": 1280, "height": 720},
            "budget": {"max_usd": budget},
        }
    )


def _run(capsys, argv, model):
    code = main(argv, planner_model=model)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_plan_mode_full_flow(capsys):
    code, out, _ = _run(
        capsys,
        ["500 variations of a robotic arm", "--budget", "50"],
        FakePlannerModel([_plan_json()]),
    )
    assert code == 0
    assert 'planning:  "500 variations of a robotic arm"' in out
    assert "planned:   arm-500" in out
    assert "verdict:   APPROVE" in out


def test_budget_flag_is_enforced_over_model_claim(capsys):
    # the fake's plan claims $999; the CLI --budget 50 must win
    code, out, _ = _run(
        capsys, ["req", "--budget", "50"], FakePlannerModel([_plan_json(budget=999.0)])
    )
    assert code == 0
    assert "budget:    $50.00" in out
    assert "$999" not in out


def test_generated_plan_is_judged_and_trimmed_by_the_gate(capsys):
    # a generated plan gets no special treatment: a redundant one is value-trimmed
    redundant = (
        _plan_json()
        .replace('"levels": 5', '"levels": 1')
        .replace('"levels": 8', '"levels": 1')
    )  # capacity collapses to 12 -> heavily redundant
    code, out, _ = _run(
        capsys, ["req", "--budget", "50"], FakePlannerModel([redundant])
    )
    assert code == 1  # MODIFY: the gate trims the planner's own waste
    assert "diversity" in out
    assert "value:" in out


def test_save_writes_a_revalidatable_plan(capsys, tmp_path):
    save = tmp_path / "generated_plan.json"
    code, out, _ = _run(
        capsys,
        ["req", "--budget", "50", "--save", str(save)],
        FakePlannerModel([_plan_json()]),
    )
    assert code == 0
    assert f"saved:     {save}" in out
    reloaded = GenerationPlan.model_validate(json.loads(save.read_text()))
    assert reloaded.plan_id == "arm-500"
    assert reloaded.budget.max_usd == 50.0  # the enforced budget is what got saved


def test_planning_failure_exits_3(capsys):
    code, _, err = _run(
        capsys, ["req", "--budget", "50"], FakePlannerModel(["bad", "bad", "bad"])
    )
    assert code == 3
    assert "planning failed" in err


def test_evaluate_mode_unaffected_by_plan_mode(capsys, tmp_path):
    # no --budget -> target is a file path, exactly as before M6
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(_plan_json(budget=50.0))
    code = main([str(plan_file)])
    out = capsys.readouterr().out
    assert code == 0
    assert "verdict:   APPROVE" in out
