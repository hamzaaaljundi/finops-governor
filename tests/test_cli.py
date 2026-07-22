"""CLI tests (minimal entry point, pulled forward from M8)."""

import json
from pathlib import Path


from finops_governor.cli import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_approve_exits_0(capsys):
    code, out, _ = _run(capsys, str(FIXTURES / "plans" / "valid" / "minimal.json"))
    assert code == 0
    assert "verdict:   APPROVE" in out


def test_block_exits_2(capsys):
    block_fixture = sorted((FIXTURES / "gate" / "block").glob("*.json"))[0]
    code, out, _ = _run(capsys, str(block_fixture))
    assert code == 2
    assert "verdict:   BLOCK" in out


def test_modify_exits_1_and_prints_proposal(capsys):
    modify_fixture = sorted((FIXTURES / "gate" / "modify").glob("*.json"))[0]
    code, out, _ = _run(capsys, str(modify_fixture))
    assert code == 1
    assert "verdict:   MODIFY" in out
    assert "proposal:" in out


def test_redundancy_is_flagged_and_value_trimmed(capsys):
    code, out, _ = _run(capsys, str(FIXTURES / "diversity" / "redundant" / "production_scale.json"))
    assert code == 1  # ADR 0007: redundancy is MODIFIABLE
    assert "$929.97" in out  # the waste, priced (session-3 constants, ADR 0009)
    assert "value:" in out and "50000 -> 26" in out  # and the plan without it
    assert "$0.50" in out


def test_profile_flag(capsys):
    code, out, _ = _run(
        capsys, str(FIXTURES / "plans" / "valid" / "minimal.json"), "--profile", "h100"
    )
    assert code == 0
    assert "H100" in out


def test_missing_file_exits_3(capsys):
    code, _, err = _run(capsys, "no_such_plan.json")
    assert code == 3
    assert "no such file" in err


def test_invalid_plan_exits_3(capsys, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"plan_id": "x"}))  # missing required fields
    code, _, err = _run(capsys, str(bad))
    assert code == 3
    assert "not a valid GenerationPlan" in err


def test_unknown_profile_exits_3(capsys):
    code, _, err = _run(
        capsys, str(FIXTURES / "plans" / "valid" / "minimal.json"), "--profile", "tpu9"
    )
    assert code == 3
    assert "unknown hardware profile" in err


# ---------------------------------------------------------------------- #
# Portfolio mode (M10, ADR 0010)
# ---------------------------------------------------------------------- #


def test_portfolio_mode_allocates_across_jobs(capsys, tmp_path):
    import copy

    base = json.loads((FIXTURES / "diversity" / "redundant" / "production_scale.json").read_text())
    base["budget"]["max_usd"] = 1_000_000

    def write(name: str, variations: int, levels: list[tuple[str, int]]) -> str:
        d = copy.deepcopy(base)
        d["plan_id"] = name
        d["scenes"][0]["variation_count"] = variations
        d["scenes"][0]["randomization"]["parameters"] = [
            {"name": n, "levels": lv} for n, lv in levels
        ]
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(d))
        return str(path)

    job_a = write("job-A", 20000, [("axis0", 50), ("axis1", 50)])
    job_b = write("job-B", 20000, [("axis0", 200)])

    code, out, _ = _run(capsys, "--portfolio", job_a, job_b, "--portfolio-budget", "5.0")
    assert code == 0
    assert "portfolio: 2 jobs" in out
    assert "budget:    $5.00" in out
    assert "total:" in out


def test_portfolio_requires_portfolio_budget(capsys):
    code, _, err = _run(capsys, "--portfolio", str(FIXTURES / "plans" / "valid" / "minimal.json"))
    assert code == 3
    assert "--portfolio-budget" in err


def test_portfolio_and_target_conflict(capsys):
    code, _, err = _run(
        capsys,
        str(FIXTURES / "plans" / "valid" / "minimal.json"),
        "--portfolio",
        str(FIXTURES / "plans" / "valid" / "minimal.json"),
        "--portfolio-budget",
        "5.0",
    )
    assert code == 3
    assert "drop TARGET" in err


def test_portfolio_rejects_multi_scene_job(capsys):
    code, _, err = _run(
        capsys,
        "--portfolio",
        str(FIXTURES / "plans" / "valid" / "multi_scene.json"),
        "--portfolio-budget",
        "5.0",
    )
    assert code == 3
    assert "exactly one scene" in err


def test_no_target_no_portfolio_exits_3(capsys):
    code, _, err = _run(capsys)
    assert code == 3
    assert "TARGET is required" in err


def test_portfolio_out_writes_round_trippable_json(capsys, tmp_path):
    import copy

    from finops_governor.portfolio import PortfolioResult

    base = json.loads((FIXTURES / "diversity" / "redundant" / "production_scale.json").read_text())
    base["budget"]["max_usd"] = 1_000_000
    d = copy.deepcopy(base)
    d["plan_id"] = "job-A"
    plan_path = tmp_path / "job_a.json"
    plan_path.write_text(json.dumps(d))
    out_path = tmp_path / "result.json"

    code, out, _ = _run(
        capsys,
        "--portfolio",
        str(plan_path),
        "--portfolio-budget",
        "5.0",
        "--portfolio-out",
        str(out_path),
    )
    assert code == 0
    assert f"result:    {out_path}" in out
    # round-trippable: the written JSON validates back into a PortfolioResult
    result = PortfolioResult.model_validate_json(out_path.read_text())
    assert result.budget_usd == 5.0
    assert result.jobs[0].plan_id == "job-A"


def test_portfolio_out_requires_portfolio(capsys):
    code, _, err = _run(
        capsys,
        str(FIXTURES / "plans" / "valid" / "minimal.json"),
        "--portfolio-out",
        "/tmp/x.json",
    )
    assert code == 3
    assert "--portfolio-out requires --portfolio" in err
