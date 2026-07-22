"""Command-line entry point (CLI at M5, plan mode at M6, full pipeline at M7,
portfolio mode at M10).

Three modes:

  Evaluate a plan file (no --budget, no --portfolio) - ONE gate pass, the gate's own
  interface:
      python -m finops_governor plan.json [--profile h100] [--geometry]
      exit: 0 = APPROVE, 1 = MODIFY (proposal printed), 2 = BLOCK, 3 = invalid input

  Plan from natural language - the FULL pipeline (M7): plan -> gate -> adopt-on-modify
  -> re-gate -> execute stub, with the audit trail as the output:
      python -m finops_governor "500 arm variations" --budget 50 [--audit audit.json]
      exit: 0 = EXECUTED, 2 = BLOCKED, 3 = FAILED or invalid input
      (there is no exit 1 in plan mode: MODIFY is adopted automatically - the gate's
      proposal becomes the plan, deterministically, per ADR 0007/0008)

  Portfolio - one shared budget across N single-scene plans (M10, ADR 0010):
      python -m finops_governor --portfolio a.json b.json c.json --portfolio-budget 50
      exit: 0 = allocation computed (some jobs may still be excluded or underfunded),
      3 = invalid input (a multi-scene plan, a missing file, missing --portfolio-budget)

--save writes the FINAL plan (as it would run, post-adoption); --audit writes the full
terminal PipelineState - the dollars-saved receipt.
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from finops_governor.advisor import advise
from finops_governor.estimator import GpuRenderCostModel, HardwareProfile, get_profile
from finops_governor.gate.decision import GateDecision, Verdict
from finops_governor.governor import Governor
from finops_governor.orchestration import PipelineState, PipelineStatus, Orchestrator
from finops_governor.planner import Planner, PlannerModel
from finops_governor.schemas import GenerationPlan

_EXIT = {Verdict.APPROVE: 0, Verdict.MODIFY: 1, Verdict.BLOCK: 2}
_EXIT_STATUS = {
    PipelineStatus.EXECUTED: 0,
    PipelineStatus.BLOCKED: 2,
    PipelineStatus.FAILED: 3,
}


def main(argv: list[str] | None = None, planner_model: PlannerModel | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="finops-governor",
        description=(
            "Deterministic pre-flight gate for synthetic-data GPU spend: evaluates a "
            "GenerationPlan (or runs the full plan->gate->execute pipeline from "
            "natural language with --budget) before any GPU spend, or allocates one "
            "shared budget across many jobs with --portfolio."
        ),
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help=(
            "path to a GenerationPlan JSON file; or, with --budget, a natural-language "
            "request. Omit when using --portfolio."
        ),
    )
    parser.add_argument(
        "--portfolio",
        nargs="+",
        default=None,
        metavar="PLAN",
        help=(
            "M10: allocate one shared budget (--portfolio-budget) across multiple "
            "GenerationPlan JSON files, each declaring exactly one scene (ADR 0010)"
        ),
    )
    parser.add_argument(
        "--portfolio-budget",
        type=float,
        default=None,
        metavar="USD",
        help="--portfolio requires this: the one shared budget being allocated",
    )
    parser.add_argument(
        "--portfolio-out",
        default=None,
        metavar="PATH",
        help="portfolio mode: also write the full PortfolioResult as JSON to PATH",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="plan mode: treat TARGET as a request; run the full pipeline under this budget (USD)",
    )
    parser.add_argument(
        "--save",
        default=None,
        metavar="PATH",
        help="plan mode: write the final plan (as it would run) to PATH",
    )
    parser.add_argument(
        "--audit",
        default=None,
        metavar="PATH",
        help="plan mode: write the full audit trail (terminal pipeline state) to PATH",
    )
    parser.add_argument(
        "--emit-replicator",
        default=None,
        metavar="PATH",
        help=(
            "evaluate mode: also write a runnable Omniverse Replicator script for "
            "this plan to PATH (single-scene plans; see finops_governor.adapter)"
        ),
    )
    parser.add_argument(
        "--advise",
        action="store_true",
        help="also rank all hardware profiles by this job's cost and recommend the cheapest",
    )
    parser.add_argument(
        "--profile",
        default="a10g",
        help="hardware profile for the cost model (default: a10g)",
    )
    parser.add_argument(
        "--geometry",
        action="store_true",
        help=(
            "also run the USD geometry axis; requires each scene's stage path "
            "(environment usd_path) to resolve on disk"
        ),
    )
    args = parser.parse_args(argv)

    try:
        profile = get_profile(args.profile)
    except KeyError:
        print(f"error: unknown hardware profile: {args.profile}", file=sys.stderr)
        return 3

    cost_model = GpuRenderCostModel(profile)
    governor = (
        Governor.with_all_checks(cost_model)
        if args.geometry
        else Governor.with_default_checks(cost_model)
    )

    if args.portfolio is not None:
        if args.portfolio_budget is None:
            print("error: --portfolio requires --portfolio-budget", file=sys.stderr)
            return 3
        if args.target is not None:
            print(
                "error: --portfolio takes its plans as its own argument; drop TARGET",
                file=sys.stderr,
            )
            return 3
        return _run_portfolio(args, profile, cost_model, governor)

    if args.portfolio_budget is not None:
        print("error: --portfolio-budget requires --portfolio", file=sys.stderr)
        return 3

    if args.portfolio_out is not None:
        print("error: --portfolio-out requires --portfolio", file=sys.stderr)
        return 3

    if args.target is None:
        print(
            "error: TARGET is required (a plan file, a request with --budget, or use --portfolio)",
            file=sys.stderr,
        )
        return 3

    if args.budget is not None:
        if args.emit_replicator is not None:
            print(
                "error: --emit-replicator requires evaluate mode "
                "(save the final plan with --save, then adapt it)",
                file=sys.stderr,
            )
            return 3
        return _run_pipeline(args, profile, governor, planner_model)

    if args.audit is not None:
        print("error: --audit requires plan mode (--budget)", file=sys.stderr)
        return 3

    plan = _load_plan_file(args.target)
    if plan is None:
        return 3
    decision = governor.evaluate(plan)
    _print_decision(plan, profile, decision)
    if args.advise:
        _print_advice(plan)
    if args.emit_replicator is not None:
        from finops_governor.adapter import AdapterError, generate_replicator_script

        try:
            script = generate_replicator_script(plan)
        except AdapterError as exc:
            print(f"error: cannot adapt plan: {exc}", file=sys.stderr)
            return 3
        Path(args.emit_replicator).write_text(script)
        print(f"replicator: {args.emit_replicator}")
    return _EXIT[decision.verdict]


# ---------------------------------------------------------------------- #
# Plan mode: the full pipeline (M7)
# ---------------------------------------------------------------------- #


def _run_pipeline(
    args: argparse.Namespace,
    profile: HardwareProfile,
    governor: Governor,
    planner_model: PlannerModel | None,
) -> int:
    if planner_model is None:
        # Deferred: only plan mode needs the SDK (and a key at request time).
        from finops_governor.planner import AnthropicPlannerModel

        planner_model = AnthropicPlannerModel()

    print(f'pipeline:  "{args.target}"  (budget ${args.budget:,.2f}, {profile.name})')
    orchestrator = Orchestrator(Planner(planner_model), governor)
    try:
        final = orchestrator.run(args.target, budget_usd=args.budget)
    except Exception as exc:  # SDK errors: missing ANTHROPIC_API_KEY, network, auth
        print(
            f"error: model call failed ({type(exc).__name__}: {exc}). Is ANTHROPIC_API_KEY set?",
            file=sys.stderr,
        )
        return 3

    for event in final.events:
        axes = f" [{', '.join(event.driving_axes)}]" if event.driving_axes else ""
        print(f"  {event.sequence + 1}. {event.node:8s}{axes} {event.summary}")

    print(f"status:    {final.status.value}")
    savings = _savings(final)
    if final.status is PipelineStatus.EXECUTED and final.decision is not None:
        line = (
            f"final:     ${final.decision.estimate.total_usd:,.2f} of "
            f"${final.budget_usd:,.2f} budget"
        )
        if savings > 0:
            line += f" (${savings:,.2f} of predictably wasted spend removed)"
        print(line)
    if final.status is PipelineStatus.FAILED and final.error is not None:
        print(f"error: {final.error}", file=sys.stderr)

    if args.advise and final.plan is not None:
        _print_advice(final.plan)

    if args.save is not None and final.plan is not None:
        Path(args.save).write_text(final.plan.model_dump_json(indent=2) + "\n")
        print(f"saved:     {args.save}")
    if args.audit is not None:
        Path(args.audit).write_text(final.model_dump_json(indent=2) + "\n")
        print(f"audit:     {args.audit}")

    return _EXIT_STATUS[final.status]


def _savings(final: PipelineState) -> float:
    """Dollars removed by adoption: first gate estimate minus final estimate."""
    if final.decision is None or not any(e.node == "adopt" for e in final.events):
        return 0.0
    first_gate = next(e for e in final.events if e.node == "gate")
    if first_gate.estimated_usd is None:
        return 0.0  # pragma: no cover
    return first_gate.estimated_usd - final.decision.estimate.total_usd


# ---------------------------------------------------------------------- #
# Portfolio mode: one shared budget across N jobs (M10, ADR 0010)
# ---------------------------------------------------------------------- #


def _run_portfolio(
    args: argparse.Namespace,
    profile: HardwareProfile,
    cost_model: GpuRenderCostModel,
    governor: Governor,
) -> int:
    from finops_governor.portfolio import allocate_portfolio

    plans = []
    for path_str in args.portfolio:
        plan = _load_plan_file(path_str)
        if plan is None:
            return 3
        plans.append(plan)

    try:
        result = allocate_portfolio(
            plans, budget_usd=args.portfolio_budget, cost_model=cost_model, governor=governor
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    print(f"portfolio: {len(plans)} jobs, {profile.name}")
    print(f"budget:    ${result.budget_usd:,.2f}")
    for job in result.jobs:
        marker = "included" if job.included else "excluded"
        print(
            f"  {job.plan_id:20s} {marker:9s} "
            f"n={job.allocated_variation_count}/{job.requested_variation_count:<8} "
            f"${job.allocated_cost_usd:<10,.4f} "
            f"distinct={job.expected_distinct:<10,.2f} {job.reason}"
        )
    print(
        f"total:     ${result.total_cost_usd:,.2f} spent, {result.total_expected_distinct:,.2f} expected distinct"
    )
    if args.portfolio_out is not None:
        Path(args.portfolio_out).write_text(result.model_dump_json(indent=2) + "\n")
        print(f"result:    {args.portfolio_out}")
    return 0


# ---------------------------------------------------------------------- #
# Evaluate mode: one gate pass (unchanged contract)
# ---------------------------------------------------------------------- #


def _load_plan_file(path_str: str) -> GenerationPlan | None:
    path = Path(path_str)
    if not path.is_file():
        print(f"error: no such file: {path}", file=sys.stderr)
        return None
    try:
        return GenerationPlan.model_validate(json.loads(path.read_text()))
    except (json.JSONDecodeError, ValidationError) as exc:
        print(f"error: not a valid GenerationPlan: {exc}", file=sys.stderr)
        return None


def _print_decision(plan: GenerationPlan, profile: HardwareProfile, decision: GateDecision) -> None:
    print(f"plan:      {plan.plan_id}")
    print(f"profile:   {profile.name}")
    print(
        f"estimated: ${decision.estimate.total_usd:,.2f}  "
        f"({decision.estimate.total_images:,} images, "
        f"{decision.estimate.total_gpu_hours:.2f} GPU-hours)"
    )
    print(f"budget:    ${decision.budget_usd:,.2f}")
    print(f"verdict:   {decision.verdict.value}")
    if decision.reason:
        print(f"findings:  {decision.reason}")
    if decision.verdict is Verdict.MODIFY and decision.modified_estimate is not None:
        print(
            f"proposal:  fits budget at ${decision.modified_estimate.total_usd:,.2f} "
            f"({'; '.join(decision.modifications)})"
        )


def _print_advice(plan: GenerationPlan) -> None:
    advice = advise(plan)
    print("advice:    cheapest hardware for this job:")
    for row in advice.ranking:
        marker = "  <- recommended" if row.profile_id == advice.recommended_profile_id else ""
        print(
            f"             {row.profile_id:6s} ${row.total_usd:,.2f}  "
            f"({row.gpu_hours:.2f} GPU-hours @ ${row.price_per_hour_usd}/h){marker}"
        )
    if advice.max_savings_usd > 0:
        print(
            f"             picking the most expensive would cost "
            f"${advice.max_savings_usd:,.2f} more"
        )


if __name__ == "__main__":
    raise SystemExit(main())
