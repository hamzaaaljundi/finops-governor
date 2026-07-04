"""Validity contract tests (M3, Task 3.1)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.schemas import GenerationPlan
from finops_governor.validity import (
    CheckContext,
    Finding,
    Severity,
    ValidityCheck,
    ValidityReport,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plans" / "valid"


@pytest.fixture(scope="module")
def context() -> CheckContext:
    plan = GenerationPlan.model_validate(
        json.loads((FIXTURES / "minimal.json").read_text())
    )
    estimate = GpuRenderCostModel(get_profile("a10g")).estimate(plan)
    return CheckContext(plan=plan, cost_estimate=estimate)


def _finding(sev: Severity, name: str = "test") -> Finding:
    return Finding(check_name=name, severity=sev, reason="because")


def test_context_carries_plan_and_estimate(context):
    assert context.plan.plan_id == "plan-minimal-001"
    assert context.cost_estimate.total_images == 1


def test_context_is_frozen(context):
    with pytest.raises(ValidationError):
        context.cost_estimate = context.cost_estimate  # any assignment is blocked


def test_finding_is_frozen():
    f = _finding(Severity.WARNING)
    with pytest.raises(ValidationError):
        f.reason = "mutated"


def test_finding_requires_non_empty_fields():
    with pytest.raises(ValidationError):
        Finding(check_name="", severity=Severity.WARNING, reason="r")


def test_empty_report_is_clean():
    report = ValidityReport()
    assert report.is_clean
    assert not report.has_blocking
    assert not report.has_modifiable
    assert report.warnings == ()


def test_report_severity_queries():
    report = ValidityReport(
        findings=(
            _finding(Severity.WARNING, "diversity"),
            _finding(Severity.BLOCKING, "geometry"),
            _finding(Severity.MODIFIABLE, "cost"),
        )
    )
    assert not report.is_clean
    assert report.has_blocking
    assert report.has_modifiable
    assert len(report.warnings) == 1
    assert report.warnings[0].check_name == "diversity"


def test_a_conforming_object_satisfies_the_interface():
    class DummyCheck:
        name = "dummy"

        def check(self, context: CheckContext) -> list[Finding]:
            return []

    assert isinstance(DummyCheck(), ValidityCheck)


def test_finding_round_trips_for_audit():
    f = Finding(
        check_name="cost",
        severity=Severity.BLOCKING,
        reason="over budget",
        detail={"estimated_usd": 1897.33, "budget_usd": 1000.0},
    )
    assert Finding.model_validate_json(f.model_dump_json()) == f


def test_report_round_trips_for_audit():
    report = ValidityReport(findings=(_finding(Severity.WARNING),))
    assert ValidityReport.model_validate_json(report.model_dump_json()) == report
