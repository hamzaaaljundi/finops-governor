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
    assert "$373.18" in out  # the waste, priced
    assert "value:" in out and "50000 -> 26" in out  # and the plan without it
    assert "$0.20" in out


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
