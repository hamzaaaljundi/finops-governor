"""Command-line entry point (pulled forward from M8).

The minimal ignition for the engine: evaluate a GenerationPlan JSON through the
multi-axis Governor and print the verdict, the findings, and the money.

    python -m finops_governor plan.json
    python -m finops_governor plan.json --profile h100

Exit code mirrors the verdict so the CLI composes into pipelines like the gate it is:
0 = APPROVE, 1 = MODIFY (a fitting variant exists), 2 = BLOCK, 3 = invalid input.
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.gate.decision import Verdict
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan

_EXIT = {Verdict.APPROVE: 0, Verdict.MODIFY: 1, Verdict.BLOCK: 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="finops-governor",
        description=(
            "Pre-flight gate for training-value-per-GPU-dollar: evaluates a "
            "GenerationPlan and decides approve / modify / block before any GPU spend."
        ),
    )
    parser.add_argument("plan", help="path to a GenerationPlan JSON file")
    parser.add_argument(
        "--profile",
        default="a10g",
        help="hardware profile for the cost model (default: a10g)",
    )
    args = parser.parse_args(argv)

    path = Path(args.plan)
    if not path.is_file():
        print(f"error: no such file: {path}", file=sys.stderr)
        return 3
    try:
        plan = GenerationPlan.model_validate(json.loads(path.read_text()))
    except (json.JSONDecodeError, ValidationError) as exc:
        print(f"error: not a valid GenerationPlan: {exc}", file=sys.stderr)
        return 3

    try:
        profile = get_profile(args.profile)
    except KeyError:
        print(f"error: unknown hardware profile: {args.profile}", file=sys.stderr)
        return 3

    governor = Governor.with_default_checks(GpuRenderCostModel(profile))
    decision = governor.evaluate(plan)

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
    return _EXIT[decision.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
