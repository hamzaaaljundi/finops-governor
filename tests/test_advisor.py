"""Profile advisor tests (M8, Task 8.2)."""

import json
from pathlib import Path

import pytest

from finops_governor.advisor import ProfileAdvice, advise
from finops_governor.cli import main
from finops_governor.schemas import GenerationPlan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def multi_scene_plan() -> GenerationPlan:
    return GenerationPlan.model_validate(
        json.loads((FIXTURES / "plans" / "valid" / "multi_scene.json").read_text())
    )


def test_ranking_is_cheapest_first(multi_scene_plan):
    advice = advise(multi_scene_plan)
    costs = [r.total_usd for r in advice.ranking]
    assert costs == sorted(costs)
    assert advice.recommended_profile_id == advice.ranking[0].profile_id
    assert advice.recommended.total_usd == advice.ranking[0].total_usd


def test_reproduces_the_m2_worked_example(multi_scene_plan):
    # cost-model.md section 6.3 with session-3 measured constants (ADR 0009): the
    # mid-tier A10G still beats both the cheapest-per-hour (T4) and the fastest
    # (H100) on this fixed-overhead-heavy job - the punchline survived
    # recalibration, with a narrowed gap (a10g $0.96 vs h100 $0.99, ~2.4%)
    advice = advise(multi_scene_plan)
    assert advice.recommended_profile_id == "a10g"
    assert [r.profile_id for r in advice.ranking] == ["a10g", "h100", "t4"]
    assert advice.ranking[0].total_usd == pytest.approx(0.96, abs=0.01)
    assert advice.ranking[2].total_usd == pytest.approx(1.24, abs=0.01)


def test_max_savings_is_worst_minus_best(multi_scene_plan):
    advice = advise(multi_scene_plan)
    expected = advice.ranking[-1].total_usd - advice.ranking[0].total_usd
    assert advice.max_savings_usd == pytest.approx(expected, abs=1e-6)


def test_fits_budget_flags(multi_scene_plan):
    advice = advise(multi_scene_plan)  # budget $2500: everything fits
    assert all(r.fits_budget for r in advice.ranking)


def test_advice_is_frozen_and_round_trips(multi_scene_plan):
    advice = advise(multi_scene_plan)
    restored = ProfileAdvice.model_validate(json.loads(advice.model_dump_json()))
    assert restored == advice


def test_cli_advise_flag_in_evaluate_mode(capsys):
    code = main([str(FIXTURES / "plans" / "valid" / "multi_scene.json"), "--advise"])
    out = capsys.readouterr().out
    assert code == 0
    assert "advice:" in out
    assert "<- recommended" in out
    assert out.index("verdict:") < out.index("advice:")


def test_cli_without_advise_stays_quiet(capsys):
    code = main([str(FIXTURES / "plans" / "valid" / "multi_scene.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "advice:" not in out
