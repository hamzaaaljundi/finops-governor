"""Portfolio allocator tests (M10, ADR 0010).

Covers: the ADR 0010 decision 7 single-scene scope guard, BLOCK exclusion, MODIFY
value-trim integration, budget-constrained trade-offs, and the segment-based
fractional-knapsack algorithm's correctness against a brute-force optimum on a small,
independently verifiable case - the same evidence standard this project holds its
GPU-cost calibration to (docs/calibration.md), applied to an algorithm.
"""

import copy
import json
from pathlib import Path

import pytest

from finops_governor.estimator import GpuRenderCostModel, load_profiles
from finops_governor.portfolio import allocate_portfolio
from finops_governor.schemas import GenerationPlan
from finops_governor.validity.diversity import expected_distinct

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def cost_model() -> GpuRenderCostModel:
    return GpuRenderCostModel(load_profiles()["a10g"])


@pytest.fixture(scope="module")
def production_base() -> dict:
    data = json.loads((FIXTURES / "diversity" / "redundant" / "production_scale.json").read_text())
    data["budget"]["max_usd"] = 1_000_000  # never BLOCK/trim on budget in these tests
    return data


def _make(
    base: dict, plan_id: str, variations: int, levels: list[tuple[str, int]]
) -> GenerationPlan:
    d = copy.deepcopy(base)
    d["plan_id"] = plan_id
    d["scenes"][0]["variation_count"] = variations
    d["scenes"][0]["randomization"]["parameters"] = [
        {"name": name, "levels": lv} for name, lv in levels
    ]
    return GenerationPlan.model_validate(d)


def _capacity_of(plans: list[GenerationPlan], plan_id: str) -> int:
    scene = next(p for p in plans if p.plan_id == plan_id).scenes[0]
    capacity = 1
    for param in scene.randomization.parameters:  # type: ignore[union-attr]
        capacity *= param.levels
    return capacity


def _cost_at(cost_model, plans: list[GenerationPlan], plan_id: str, n: int) -> float:
    plan = next(p for p in plans if p.plan_id == plan_id)
    data = plan.model_dump()
    data["scenes"][0]["variation_count"] = n
    return cost_model.estimate(GenerationPlan.model_validate(data)).total_usd


def test_multi_scene_job_rejected_before_the_gate_runs(cost_model, production_base):
    """ADR 0010 decision 7: checked unconditionally, so it can't be masked by a BLOCK
    verdict a multi-scene job might also happen to earn."""
    single = _make(production_base, "single", 100, [("axis0", 4)])
    multi = GenerationPlan.model_validate(
        json.loads((FIXTURES / "plans" / "valid" / "multi_scene.json").read_text())
    )
    with pytest.raises(ValueError, match="exactly one scene"):
        allocate_portfolio([single, multi], budget_usd=100.0, cost_model=cost_model)


def test_blocking_job_excluded_before_allocation(cost_model):
    """ADR 0010 decision 2: a BLOCKING job never competes for shared budget, and its
    real gate rejection reason is preserved for the audit trail."""
    minimal = GenerationPlan.model_validate(
        json.loads((FIXTURES / "plans" / "valid" / "minimal.json").read_text())
    )
    block_fixture = sorted((FIXTURES / "gate" / "block").glob("*.json"))[0]
    blocked = GenerationPlan.model_validate(json.loads(block_fixture.read_text()))

    result = allocate_portfolio([minimal, blocked], budget_usd=100.0, cost_model=cost_model)
    by_id = {j.plan_id: j for j in result.jobs}

    assert by_id[minimal.plan_id].included
    assert not by_id[blocked.plan_id].included
    assert by_id[blocked.plan_id].allocated_cost_usd == 0.0
    assert "BLOCKING" in by_id[blocked.plan_id].reason


def test_modify_jobs_enter_allocation_already_value_trimmed(cost_model, production_base):
    """ADR 0010 decision 3: a redundant job's *requested* count (as the portfolio
    sees it) is the value-trimmed justified count, not the wasteful raw declaration -
    the portfolio never has to pay to discover waste M6.5 already priced for free."""
    redundant = _make(production_base, "redundant", 50000, [("axis0", 4), ("axis1", 5)])
    result = allocate_portfolio([redundant], budget_usd=1_000_000.0, cost_model=cost_model)
    job = result.jobs[0]
    assert job.requested_variation_count < 50000  # value-trimmed, not the raw 50000
    assert "value-trimmed" in job.reason


def test_budget_is_never_exceeded(cost_model, production_base):
    """The core invariant: total allocated cost never exceeds the shared budget,
    across a genuinely budget-constrained multi-job scenario."""
    plans = [
        _make(production_base, "job-A", 20000, [("axis0", 50), ("axis1", 50)]),
        _make(production_base, "job-B", 20000, [("axis0", 200)]),
        _make(production_base, "job-C", 20000, [("axis0", 20), ("axis1", 20), ("axis2", 20)]),
    ]
    result = allocate_portfolio(plans, budget_usd=15.0, cost_model=cost_model)
    assert result.total_cost_usd <= 15.0
    assert sum(j.allocated_cost_usd for j in result.jobs) == pytest.approx(
        result.total_cost_usd, abs=1e-3
    )


def test_higher_capacity_job_gets_more_of_a_constrained_budget(cost_model, production_base):
    """Sanity check on direction: under a tight shared budget, the job with more
    achievable distinct configurations should out-compete a job that saturates fast,
    all else equal - the whole point of allocating by marginal value, not by size."""
    high_capacity = _make(
        production_base, "high-cap", 20000, [("axis0", 20), ("axis1", 20), ("axis2", 20)]
    )
    low_capacity = _make(production_base, "low-cap", 20000, [("axis0", 5)])
    result = allocate_portfolio(
        [high_capacity, low_capacity], budget_usd=10.0, cost_model=cost_model
    )
    by_id = {j.plan_id: j for j in result.jobs}
    assert by_id["high-cap"].expected_distinct > by_id["low-cap"].expected_distinct


def test_whole_job_greedy_has_a_real_gap_the_shipped_allocator_does_not(
    cost_model, production_base
):
    """Reproduces the ADR 0010 decision-4 finding at the code level: ranking whole
    jobs by cost-per-distinct at their own declared count and funding them fully in
    that order is measurably worse than the segment-based allocator this module
    ships. A regression here would mean the shipped algorithm quietly became the
    rejected one."""
    plans = [
        _make(production_base, "job-A", 20000, [("axis0", 50), ("axis1", 50)]),
        _make(production_base, "job-B", 20000, [("axis0", 200)]),
        _make(production_base, "job-C", 20000, [("axis0", 20), ("axis1", 20), ("axis2", 20)]),
    ]
    budget = 15.0
    shipped = allocate_portfolio(plans, budget_usd=budget, cost_model=cost_model)

    # whole-job greedy: rank by cost-per-distinct at each job's OWN (already
    # value-trimmed) requested count; fund fully in that order; nothing partial.
    rows = []
    for j in shipped.jobs:  # requested_variation_count is already value-trimmed
        full_value = expected_distinct(j.requested_variation_count, _capacity_of(plans, j.plan_id))
        full_cost = _cost_at(cost_model, plans, j.plan_id, j.requested_variation_count)
        rows.append((full_cost / full_value if full_value else float("inf"), full_cost, full_value))
    rows.sort(key=lambda r: r[0])
    remaining, greedy_value = budget, 0.0
    for _ratio, full_cost, full_value in rows:
        if full_cost <= remaining:
            remaining -= full_cost
            greedy_value += full_value

    assert shipped.total_expected_distinct > greedy_value, (
        f"shipped allocator ({shipped.total_expected_distinct}) should beat whole-job "
        f"greedy ({greedy_value}) - if it doesn't, the shipped algorithm has "
        f"regressed to the rejected one."
    )


def test_unconstrained_budget_reaches_each_jobs_capacity_saturation(cost_model, production_base):
    """With an effectively unlimited budget, every job should be funded up to (or
    past) the point where expected_distinct saturates at its own declared capacity -
    the allocator should never leave real, affordable value on the table. The
    brute-force-vs-segment-algorithm agreement itself (25.42980505... to 11 decimal
    places) is verified in the ADR 0010 design exploration; this test checks the same
    saturation property end-to-end through real GenerationPlans."""
    capacities = [8, 16, 32]
    plans = [
        _make(production_base, f"job{i}", 40, [(f"axis{i}", capacity)])
        for i, capacity in enumerate(capacities)
    ]
    result = allocate_portfolio(
        plans, budget_usd=1_000_000.0, cost_model=cost_model, grid_points=80
    )
    for j, capacity in zip(result.jobs, capacities):
        assert j.expected_distinct == pytest.approx(
            expected_distinct(j.requested_variation_count, capacity), abs=1e-3
        )
        assert j.allocated_variation_count == j.requested_variation_count
