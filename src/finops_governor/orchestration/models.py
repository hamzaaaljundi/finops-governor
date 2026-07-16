"""Pipeline state and audit contracts (M7, Task 7.2).

The single typed, immutable state object the node functions pass along, and the audit
event each node appends. Contracts before behavior (docs/orchestration-model.md,
sections 4-5): frozen models, JSON-round-trippable, no hidden mutation - the same
discipline as GateDecision.

The audit trail is the milestone's real deliverable: `driving_axes` on gate events
answers the reviewer's question - which check drove this decision - and a trail
containing an adoption records original vs adopted estimates: the audit log of a
governed job is the dollars-saved receipt.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from finops_governor.gate.decision import GateDecision, Verdict
from finops_governor.schemas import GenerationPlan


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PipelineStatus(str, Enum):
    RUNNING = "RUNNING"
    EXECUTED = "EXECUTED"  # approve path completed (execution stub recorded the job)
    BLOCKED = "BLOCKED"  # the gate said block: a successful governance outcome
    FAILED = "FAILED"  # planner exhaustion or invariant violation; error is set


class AuditEvent(BaseModel):
    """One node execution, recorded. Frozen and serializable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int = Field(ge=0)
    node: str
    timestamp: datetime = Field(default_factory=_utc_now)
    summary: str
    verdict: Verdict | None = None
    driving_axes: tuple[str, ...] | None = None
    estimated_usd: float | None = None
    budget_usd: float | None = None
    detail: dict[str, Any] | None = None


class PipelineState(BaseModel):
    """The one state object the pipeline threads through its nodes.

    Nodes never mutate: each returns a new state via `model_copy` / `with_event`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: str | None = None
    budget_usd: float
    plan: GenerationPlan | None = None
    decision: GateDecision | None = None
    gate_passes: int = 0
    status: PipelineStatus = PipelineStatus.RUNNING
    error: str | None = None
    events: tuple[AuditEvent, ...] = ()

    def with_event(
        self,
        node: str,
        summary: str,
        *,
        verdict: Verdict | None = None,
        driving_axes: tuple[str, ...] | None = None,
        estimated_usd: float | None = None,
        budget_usd: float | None = None,
        detail: dict[str, Any] | None = None,
        **state_updates: Any,
    ) -> "PipelineState":
        """Return a new state with an audit event appended (sequence auto-assigned)
        and any other state fields updated in the same step."""
        event = AuditEvent(
            sequence=len(self.events),
            node=node,
            summary=summary,
            verdict=verdict,
            driving_axes=driving_axes,
            estimated_usd=estimated_usd,
            budget_usd=budget_usd,
            detail=detail,
        )
        return self.model_copy(update={"events": (*self.events, event), **state_updates})
