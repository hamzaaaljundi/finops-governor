"""CLI plan-mode tests (M6 Task 6.5; upgraded to the full pipeline in M7 Task 7.5).

Plan mode runs the Orchestrator: MODIFY is adopted automatically, so plan-mode exit
codes map from terminal status (EXECUTED=0, BLOCKED=2, FAILED=3) - there is no exit 1.
Driven through main() with an injected fake model: no network, no keys.
"""

import json

from finops_governor.cli import main
from finops_governor.orchestration import PipelineState
from finops_governor.planner import FakePlannerModel
from finops_governor.schemas import GenerationPlan


def _plan_json(
    budget: float = 999.0,
    variation_count: int = 500,
    levels: tuple[int, ...] = (12, 5, 8),
) -> str:
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
                            {"name": f"p{i}", "levels": v} for i, v in enumerate(levels)
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


def test_plan_mode_runs_the_full_pipeline(capsys):
    code, out, _ = _run(
        capsys,
        ["500 variations of a robotic arm", "--budget", "50"],
        FakePlannerModel([_plan_json()]),
    )
    assert code == 0
    assert 'pipeline:  "500 variations of a robotic arm"' in out
    assert "execution stub" in out
    assert "status:    EXECUTED" in out


def test_budget_flag_is_enforced_over_model_claim(capsys):
    # the fake's plan claims $999; the CLI --budget 50 must win everywhere
    code, out, _ = _run(
        capsys, ["req", "--budget", "50"], FakePlannerModel([_plan_json(budget=999.0)])
    )
    assert code == 0
    assert "$50.00" in out
    assert "$999" not in out


def test_redundant_generated_plan_is_adopted_and_executed(capsys):
    # the gate trims the planner's waste, adopts, re-gates, executes: exit 0, receipted
    code, out, _ = _run(
        capsys,
        ["req", "--budget", "50"],
        FakePlannerModel([_plan_json(variation_count=50_000, levels=(4, 4))]),
    )
    assert code == 0
    assert "adopt" in out and "saved" in out
    assert "predictably wasted spend removed" in out
    assert "status:    EXECUTED" in out


def test_save_writes_the_final_plan_as_it_would_run(capsys, tmp_path):
    save = tmp_path / "final_plan.json"
    code, out, _ = _run(
        capsys,
        ["req", "--budget", "50", "--save", str(save)],
        FakePlannerModel([_plan_json(variation_count=50_000, levels=(4, 4))]),
    )
    assert code == 0
    reloaded = GenerationPlan.model_validate(json.loads(save.read_text()))
    assert reloaded.budget.max_usd == 50.0  # the enforced budget
    assert reloaded.scenes[0].variation_count == 26  # post-adoption: the trimmed plan


def test_audit_writes_the_round_trippable_trail(capsys, tmp_path):
    audit = tmp_path / "audit.json"
    code, out, _ = _run(
        capsys,
        ["req", "--budget", "50", "--audit", str(audit)],
        FakePlannerModel([_plan_json(variation_count=50_000, levels=(4, 4))]),
    )
    assert code == 0
    state = PipelineState.model_validate(json.loads(audit.read_text()))
    assert [e.node for e in state.events] == [
        "plan",
        "gate",
        "adopt",
        "gate",
        "execute",
    ]
    assert state.events[1].driving_axes == ("diversity",)


def test_audit_requires_plan_mode(capsys, tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(_plan_json(budget=50.0))
    code = main([str(plan_file), "--audit", str(tmp_path / "a.json")])
    err = capsys.readouterr().err
    assert code == 3
    assert "--audit requires plan mode" in err


def test_planning_failure_exits_3(capsys):
    code, out, err = _run(
        capsys, ["req", "--budget", "50"], FakePlannerModel(["bad", "bad", "bad"])
    )
    assert code == 3
    assert "status:    FAILED" in out
    assert "error:" in err


def test_evaluate_mode_unaffected_by_the_pipeline(capsys, tmp_path):
    # no --budget -> one gate pass, verdict exit codes, exactly as before M7
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(_plan_json(budget=50.0))
    code = main([str(plan_file)])
    out = capsys.readouterr().out
    assert code == 0
    assert "verdict:   APPROVE" in out
