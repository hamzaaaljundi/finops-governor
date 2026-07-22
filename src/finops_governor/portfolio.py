"""Portfolio governance (M10, ADR 0010): govern a queue, not one job.

Every gate decision up to M9 governs one plan against one budget. This module answers
the natural next question: given N candidate jobs sharing one fixed budget, how should
that budget be split to maximize total expected-distinct-coverage per dollar spent?

The obvious first instinct - rank whole jobs by cost-per-distinct at each job's own
declared variation count, fund them in that order - was implemented and measured
against a brute-force optimum before being trusted (ADR 0010, decision 4). It has a
mean gap of 20.1% from optimal across 8 synthetic portfolios (worst case 43.8%): it is
blind to a job's own diminishing-returns curve (`expected_distinct` is concave in
variation count), so it can dump an entire budget into one job that looks cheap at its
declared endpoint while funding other jobs at zero, missing their far better *early*
returns.

What ships instead: **fractional knapsack over per-job marginal segments**. Each job's
concave value curve is broken into small chunks (grid_points of them, by default 50)
between n=0 and its own declared variation count; every chunk from every job is pooled
into one list, sorted by value-per-dollar descending, and filled greedily until the
budget runs out - the textbook fractional-knapsack algorithm, just applied to segments
instead of whole jobs. This is mathematically equivalent to marginal-value
equalization ("water-filling") and was verified against a brute-force baseline: it
matches the true optimum to 11 decimal places on a small verifiable case. See
docs/portfolio-model.md for the full measurement, including the rejected whole-job
heuristic's numbers.

v1 scope (ADR 0010): each candidate job must declare exactly one scene (decision 7);
cross-job redundancy - two jobs whose declared randomization ranges overlap - is not
detected (decision 6). BLOCKING jobs never compete for budget (decision 2); MODIFIABLE
jobs enter allocation already value-trimmed (decision 3), never at their wasteful raw
cost.
"""

from pydantic import BaseModel, ConfigDict

from finops_governor.estimator.base import CostModel
from finops_governor.gate.decision import Verdict
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan
from finops_governor.validity.diversity import capacity_for_scene, expected_distinct

_DEFAULT_GRID_POINTS = 50


class PortfolioJobResult(BaseModel):
    """One job's outcome within the portfolio: what it got funded for, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str
    included: bool
    reason: str
    requested_variation_count: int
    allocated_variation_count: int
    allocated_cost_usd: float
    expected_distinct: float


class PortfolioResult(BaseModel):
    """The full allocation: every job's outcome plus portfolio-level totals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    budget_usd: float
    total_cost_usd: float
    total_expected_distinct: float
    jobs: tuple[PortfolioJobResult, ...]


class _Job:
    """Internal working state for one candidate: its base (post-gate) plan, cost
    model, and a memoized cost(n)/value(n) pair reused while building segments."""

    def __init__(self, plan_id: str, base_plan: GenerationPlan, cost_model: CostModel) -> None:
        if len(base_plan.scenes) != 1:
            raise ValueError(
                f"portfolio job '{plan_id}' declares {len(base_plan.scenes)} scenes; "
                "v1 requires exactly one scene per job (ADR 0010, decision 7)."
            )
        self.plan_id = plan_id
        self.base_plan = base_plan
        self.cost_model = cost_model
        self.declared_n = base_plan.scenes[0].variation_count
        self.capacity = capacity_for_scene(base_plan.scenes[0])

    def cost(self, n: int) -> float:
        if n <= 0:
            return 0.0
        data = self.base_plan.model_dump()
        data["scenes"][0]["variation_count"] = n
        variant = GenerationPlan.model_validate(data)
        return self.cost_model.estimate(variant).total_usd

    def value(self, n: int) -> float:
        if n <= 0:
            return 0.0
        return expected_distinct(n, self.capacity)


def _base_job(
    plan: GenerationPlan, cost_model: CostModel, governor: Governor
) -> tuple[Verdict, _Job | None, str]:
    """Run the plan through the single-job gate once. Returns the verdict, the
    post-gate job (None for BLOCK - nothing to allocate), and a human-readable
    reason for the record."""
    decision = governor.evaluate(plan)

    if decision.verdict is Verdict.BLOCK:
        return Verdict.BLOCK, None, decision.reason

    if decision.verdict is Verdict.MODIFY:
        assert decision.modified_plan is not None  # guaranteed by GateDecision's invariant
        job = _Job(plan.plan_id, decision.modified_plan, cost_model)
        return Verdict.MODIFY, job, f"value-trimmed before allocation: {decision.reason}"

    return Verdict.APPROVE, _Job(plan.plan_id, plan, cost_model), "clean"


def _segments(job: _Job, grid_points: int) -> list[tuple[float, str, int, int, float, float]]:
    """(ratio, plan_id, from_n, to_n, cost_delta, value_delta) for each grid chunk."""
    n_max = job.declared_n
    if n_max <= 0:
        return []
    step = max(1, n_max // grid_points)
    grid = sorted(set(range(0, n_max, step)) | {n_max})

    segments = []
    prev_n, prev_cost, prev_value = 0, 0.0, 0.0
    for n in grid[1:]:
        cost_n, value_n = job.cost(n), job.value(n)
        cost_delta = cost_n - prev_cost
        value_delta = value_n - prev_value
        if cost_delta > 0:
            segments.append(
                (value_delta / cost_delta, job.plan_id, prev_n, n, cost_delta, value_delta)
            )
        prev_n, prev_cost, prev_value = n, cost_n, value_n
    return segments


def allocate_portfolio(
    plans: list[GenerationPlan],
    budget_usd: float,
    cost_model: CostModel,
    governor: Governor | None = None,
    grid_points: int = _DEFAULT_GRID_POINTS,
) -> PortfolioResult:
    """Allocate one shared budget across N candidate jobs.

    Each plan is first run through the single-job gate (`governor`, default
    `Governor.with_default_checks(cost_model)`): BLOCKING plans are excluded before
    allocation runs (ADR 0010 decision 2), MODIFIABLE plans enter already
    value-trimmed (decision 3). The remaining budget is then split across all
    surviving jobs by fractional knapsack over marginal segments (decision 4).
    """
    if governor is None:
        governor = Governor.with_default_checks(cost_model)

    jobs: dict[str, _Job] = {}
    excluded: dict[str, str] = {}
    gate_reason: dict[str, str] = {}
    for plan in plans:
        if len(plan.scenes) != 1:
            raise ValueError(
                f"portfolio job '{plan.plan_id}' declares {len(plan.scenes)} scenes; "
                "v1 requires exactly one scene per job (ADR 0010, decision 7), "
                "checked before the gate runs so this can't be masked by a BLOCK verdict."
            )
        verdict, job, reason = _base_job(plan, cost_model, governor)
        if verdict is Verdict.BLOCK:
            excluded[plan.plan_id] = reason
        else:
            assert job is not None
            jobs[plan.plan_id] = job
            gate_reason[plan.plan_id] = reason

    all_segments = []
    for job in jobs.values():
        all_segments.extend(_segments(job, grid_points))
    all_segments.sort(key=lambda s: -s[0])

    allocated_n: dict[str, int] = dict.fromkeys(jobs, 0)
    allocated_cost: dict[str, float] = dict.fromkeys(jobs, 0.0)
    allocated_value: dict[str, float] = dict.fromkeys(jobs, 0.0)
    remaining = budget_usd

    for _ratio, plan_id, _from_n, to_n, cost_delta, value_delta in all_segments:
        if cost_delta <= remaining:
            allocated_n[plan_id] = to_n
            allocated_cost[plan_id] += cost_delta
            allocated_value[plan_id] += value_delta
            remaining -= cost_delta
        else:
            frac = remaining / cost_delta
            allocated_cost[plan_id] += cost_delta * frac
            allocated_value[plan_id] += value_delta * frac
            remaining = 0.0
            break  # segments are sorted best-first; nothing further can be afforded

    results = []
    for plan in plans:
        if plan.plan_id in excluded:
            results.append(
                PortfolioJobResult(
                    plan_id=plan.plan_id,
                    included=False,
                    reason=excluded[plan.plan_id],
                    requested_variation_count=plan.scenes[0].variation_count,
                    allocated_variation_count=0,
                    allocated_cost_usd=0.0,
                    expected_distinct=0.0,
                )
            )
            continue
        job = jobs[plan.plan_id]
        funded = allocated_n[plan.plan_id] > 0
        outcome = "funded" if funded else "budget exhausted before this job"
        base_reason = gate_reason[plan.plan_id]
        reason = outcome if base_reason == "clean" else f"{base_reason}; {outcome}"
        results.append(
            PortfolioJobResult(
                plan_id=plan.plan_id,
                included=funded,
                reason=reason,
                requested_variation_count=job.declared_n,
                allocated_variation_count=allocated_n[plan.plan_id],
                allocated_cost_usd=round(allocated_cost[plan.plan_id], 4),
                expected_distinct=round(allocated_value[plan.plan_id], 4),
            )
        )

    return PortfolioResult(
        budget_usd=budget_usd,
        total_cost_usd=round(sum(allocated_cost.values()), 4),
        total_expected_distinct=round(sum(allocated_value.values()), 4),
        jobs=tuple(results),
    )
