"""The Orchestrator (M7, Task 7.4).

The bounded loop that walks the verdict router: plan -> gate -> (execute | adopt ->
re-gate | halt). Roughly sixty lines of plain Python doing what a graph runtime would
do at this scale (ADR 0008) - each step a pure node, each step audited.

The loop is bounded defensively (docs/orchestration-model.md, section 4): the adopt
strategy's convergence invariant means two gate passes suffice, so `max_gate_passes`
exists to make violations LOUD, not to enable long loops. A violation terminates as a
FAILED state carrying the error - with the audit trail preserved, because the trail is
the deliverable even when the pipeline fails.
"""

from finops_governor.governor import Governor
from finops_governor.orchestration.models import PipelineState, PipelineStatus
from finops_governor.orchestration.nodes import (
    adopt_node,
    execute_node,
    gate_node,
    plan_node,
    route,
)
from finops_governor.planner import Planner
from finops_governor.schemas import GenerationPlan

_DEFAULT_MAX_GATE_PASSES = 3


class Orchestrator:
    """Runs the full pipeline and returns the terminal state (with its audit trail)."""

    def __init__(
        self,
        planner: Planner,
        governor: Governor,
        max_gate_passes: int = _DEFAULT_MAX_GATE_PASSES,
    ) -> None:
        self._planner = planner
        self._governor = governor
        self._max_gate_passes = max_gate_passes

    def run(self, request: str, budget_usd: float) -> PipelineState:
        """Full pipeline from a natural-language request."""
        state = PipelineState(request=request, budget_usd=budget_usd)
        state = plan_node(state, self._planner)
        return self._drive(state)

    def run_plan(self, plan: GenerationPlan) -> PipelineState:
        """Pipeline from an existing plan (skips the planner)."""
        state = PipelineState(budget_usd=plan.budget.max_usd, plan=plan)
        return self._drive(state)

    # ------------------------------------------------------------------ #

    def _drive(self, state: PipelineState) -> PipelineState:
        while True:
            next_node = route(state)
            if next_node == "halt":
                return state
            if next_node == "gate":
                if state.gate_passes >= self._max_gate_passes:
                    return state.with_event(
                        "gate",
                        (
                            "invariant violation: proposal did not converge within "
                            f"{self._max_gate_passes} gate passes"
                        ),
                        status=PipelineStatus.FAILED,
                        error=(
                            f"gate did not converge in {self._max_gate_passes} passes "
                            "(a re-gated proposal must APPROVE)"
                        ),
                    )
                state = gate_node(state, self._governor)
            elif next_node == "adopt":
                state = adopt_node(state)
            else:  # "execute"
                state = execute_node(state)
