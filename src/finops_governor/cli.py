"""Command-line entry point (pulled forward from M8; plan mode added in M6).

Two modes, selected by --budget:

  Evaluate a plan file (no --budget; budget lives in the JSON):
      python -m finops_governor plan.json
      python -m finops_governor plan.json --profile h100 --geometry

  Plan from natural language, then evaluate (--budget = the caller's ceiling):
      python -m finops_governor "500 variations of a robotic arm" --budget 50
      python -m finops_governor "..." --budget 50 --save plan.json

In plan mode the LLM proposes and the same deterministic Governor disposes - a generated
plan gets no special treatment. Exit code mirrors the verdict so the CLI composes into
pipelines like the gate it is: 0 = APPROVE, 1 = MODIFY, 2 = BLOCK, 3 = invalid input or
planning failure.
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate.decision import GateDecision, Verdict
from finops_governor.governor import Governor
from finops_governor.planner import Planner, PlannerError, PlannerModel
from finops_governor.schemas import GenerationPlan

_EXIT = {Verdict.APPROVE: 0, Verdict.MODIFY: 1, Verdict.BLOCK: 2}


def main(
    argv: list[str] | None = None, planner_model: PlannerModel | None = None
) -> int:
    parser = argparse.ArgumentParser(
        prog="finops-governor",
        description=(
            "Pre-flight gate for training-value-per-GPU-dollar: evaluates a "
            "GenerationPlan (or plans one from natural language with --budget) and "
            "decides approve / modify / block before any GPU spend."
        ),
    )
    parser.add_argument(
        "target",
        help=(
            "path to a GenerationPlan JSON file; or, with --budget, a natural-language "
            "request to plan"
        ),
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help=(
            "plan mode: treat TARGET as a natural-language request and generate a plan "
            "with this budget ceiling (USD)"
        ),
    )
    parser.add_argument(
        "--save",
        default=None,
        metavar="PATH",
        help="plan mode: also write the generated plan JSON to PATH",
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

    if args.budget is not None:
        plan = _plan_from_request(args.target, args.budget, planner_model, args.save)
        if plan is None:
            return 3
    else:
        plan = _load_plan_file(args.target)
        if plan is None:
            return 3

    cost_model = GpuRenderCostModel(profile)
    governor = (
        Governor.with_all_checks(cost_model)
        if args.geometry
        else Governor.with_default_checks(cost_model)
    )
    decision = governor.evaluate(plan)
    _print_decision(plan, profile, decision)
    return _EXIT[decision.verdict]


# ---------------------------------------------------------------------- #
# Modes
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


def _plan_from_request(
    request: str,
    budget_usd: float,
    planner_model: PlannerModel | None,
    save_path: str | None,
) -> GenerationPlan | None:
    if planner_model is None:
        # Deferred: only plan mode needs the SDK (and a key at request time).
        from finops_governor.planner import AnthropicPlannerModel

        planner_model = AnthropicPlannerModel()

    print(f'planning:  "{request}"')
    try:
        plan = Planner(planner_model).plan(request, budget_usd=budget_usd)
    except PlannerError as exc:
        print(f"error: planning failed: {exc}", file=sys.stderr)
        return None
    except Exception as exc:  # SDK errors: missing ANTHROPIC_API_KEY, network, auth
        print(
            f"error: model call failed ({type(exc).__name__}: {exc}). "
            "Is ANTHROPIC_API_KEY set?",
            file=sys.stderr,
        )
        return None

    scenes = ", ".join(f"{s.scene_id} x{s.variation_count}" for s in plan.scenes)
    print(f"planned:   {plan.plan_id} ({scenes})")

    if save_path is not None:
        Path(save_path).write_text(plan.model_dump_json(indent=2) + "\n")
        print(f"saved:     {save_path}")
    return plan


# ---------------------------------------------------------------------- #
# Output
# ---------------------------------------------------------------------- #


def _print_decision(plan: GenerationPlan, profile, decision: GateDecision) -> None:
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


if __name__ == "__main__":
    raise SystemExit(main())
