"""The pipeline nodes (M7, Task 7.3).

Pure functions over PipelineState - each takes a state (plus its one dependency),
returns a NEW state, and appends exactly one audit event. Deliberately isomorphic to
LangGraph nodes (ADR 0008): `route` is the single conditional edge.

    plan_node(state, planner)    NL request -> GenerationPlan
    gate_node(state, governor)   plan -> GateDecision (+ BLOCKED status on block)
    adopt_node(state)            MODIFY -> the gate's proposal becomes the plan
    execute_node(state)          APPROVE -> record what would run (stub) -> EXECUTED
    route(state)                 -> "gate" | "adopt" | "execute" | "halt"

Nodes trust their preconditions (the orchestrator sequences them); calling one out of
order is a programming error and raises OrchestrationError loudly.
"""

import re
from typing import Any

from finops_governor.gate.decision import GateDecision, Verdict
from finops_governor.governor import Governor
from finops_governor.orchestration.models import PipelineState, PipelineStatus
from finops_governor.planner import Planner, PlannerError

_FINDING_HEADER = re.compile(r"\[(BLOCKING|MODIFIABLE|WARNING)\] ([a-z_]+):")

_DECISIVE_SEVERITY = {Verdict.BLOCK: "BLOCKING", Verdict.MODIFY: "MODIFIABLE"}


class OrchestrationError(Exception):
    """A pipeline invariant or node precondition was violated."""


def plan_node(state: PipelineState, planner: Planner) -> PipelineState:
    """Turn the NL request into a validated plan; planner exhaustion -> FAILED."""
    if state.request is None:
        raise OrchestrationError("plan_node requires a request on the state")
    try:
        plan = planner.plan(state.request, budget_usd=state.budget_usd)
    except PlannerError as exc:
        return state.with_event(
            "plan",
            f"planning failed: {exc}",
            status=PipelineStatus.FAILED,
            error=str(exc),
        )
    scenes = ", ".join(f"{s.scene_id} x{s.variation_count}" for s in plan.scenes)
    return state.with_event(
        "plan",
        f"planned '{plan.plan_id}' ({scenes})",
        budget_usd=state.budget_usd,
        plan=plan,
    )


def gate_node(state: PipelineState, governor: Governor) -> PipelineState:
    """Evaluate the current plan; a BLOCK verdict is a terminal governance outcome."""
    if state.plan is None:
        raise OrchestrationError("gate_node requires a plan on the state")
    decision = governor.evaluate(state.plan)
    axes = _driving_axes(decision)
    updates: dict[str, Any] = {
        "decision": decision,
        "gate_passes": state.gate_passes + 1,
    }
    if decision.verdict is Verdict.BLOCK:
        updates["status"] = PipelineStatus.BLOCKED
    return state.with_event(
        "gate",
        f"verdict {decision.verdict.value} on '{decision.plan_id}': {decision.reason}",
        verdict=decision.verdict,
        driving_axes=axes or None,
        estimated_usd=decision.estimate.total_usd,
        budget_usd=decision.budget_usd,
        **updates,
    )


def adopt_node(state: PipelineState) -> PipelineState:
    """Adopt the gate's proposal as the plan (the deterministic modify strategy)."""
    decision = state.decision
    if decision is None or decision.verdict is not Verdict.MODIFY:
        raise OrchestrationError("adopt_node requires a MODIFY decision on the state")
    if decision.modified_plan is None or decision.modified_estimate is None:
        raise OrchestrationError(
            "MODIFY decision carries no proposal"
        )  # pragma: no cover
    saved = decision.estimate.total_usd - decision.modified_estimate.total_usd
    return state.with_event(
        "adopt",
        (
            f"adopted the gate's proposal: ${decision.estimate.total_usd:,.2f} -> "
            f"${decision.modified_estimate.total_usd:,.2f} (${saved:,.2f} saved)"
        ),
        estimated_usd=decision.modified_estimate.total_usd,
        budget_usd=decision.budget_usd,
        detail={"modifications": list(decision.modifications)},
        plan=decision.modified_plan,
        decision=None,  # the old decision no longer describes the current plan
    )


def execute_node(state: PipelineState) -> PipelineState:
    """Record what would run (the execution stub) and finish the pipeline."""
    decision = state.decision
    if decision is None or decision.verdict is not Verdict.APPROVE:
        raise OrchestrationError("execute_node requires an APPROVE decision")
    estimate = decision.estimate
    return state.with_event(
        "execute",
        (
            f"execution stub: would render {estimate.total_images:,} images "
            f"({estimate.total_gpu_hours:.2f} GPU-hours, "
            f"${estimate.total_usd:,.2f}) on {estimate.hardware_profile}"
        ),
        estimated_usd=estimate.total_usd,
        budget_usd=decision.budget_usd,
        detail={
            "plan_id": decision.plan_id,
            "images": estimate.total_images,
            "gpu_hours": estimate.total_gpu_hours,
        },
        status=PipelineStatus.EXECUTED,
    )


def route(state: PipelineState) -> str:
    """The verdict router - the pipeline's only branch."""
    if state.status in (
        PipelineStatus.FAILED,
        PipelineStatus.BLOCKED,
        PipelineStatus.EXECUTED,
    ):
        return "halt"
    if state.decision is None:
        return "gate"
    if state.decision.verdict is Verdict.APPROVE:
        return "execute"
    if state.decision.verdict is Verdict.MODIFY:
        return "adopt"
    return "halt"  # pragma: no cover - BLOCK already sets BLOCKED status


def _driving_axes(decision: GateDecision) -> tuple[str, ...]:
    """Which checks produced the decisive findings.

    Parses the `[SEVERITY] check_name:` headers of summarize_findings - a format this
    project owns (validity/composition.py) - at the verdict's decisive severity.
    APPROVE has no decisive findings and yields ().
    """
    decisive = _DECISIVE_SEVERITY.get(decision.verdict)
    if decisive is None or not decision.reason:
        return ()
    axes: list[str] = []
    for severity, check_name in _FINDING_HEADER.findall(decision.reason):
        if severity == decisive and check_name not in axes:
            axes.append(check_name)
    return tuple(axes)
