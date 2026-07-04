"""Validity contract - data types (M3, Task 3.1).

The shared vocabulary every validity check speaks. A check reads a CheckContext and
returns Findings; the composed gate (Task 3.3) aggregates them into one decision.

Everything here is FROZEN: a check receives read-only inputs and cannot mutate the
context, the plan, or another check's findings. This is what preserves determinism -
the verdict cannot depend on which check ran first or whether a check quietly changed
shared state.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from finops_governor.estimator.estimate import CostEstimate
from finops_governor.schemas import GenerationPlan


class FrozenModel(BaseModel):
    """Base for validity types: reject unknown fields and forbid mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Severity(str, Enum):
    """How a finding affects the verdict (composition policy lives in Task 3.4)."""

    BLOCKING = "BLOCKING"  # must not run; not auto-recoverable
    MODIFIABLE = "MODIFIABLE"  # over threshold but recoverable (currently: cost only)
    WARNING = "WARNING"  # advisory; does not by itself change the verdict


class Finding(FrozenModel):
    """One problem raised by one check. Actionable and auditable, never a bare boolean."""

    check_name: str = Field(..., min_length=1)
    severity: Severity
    reason: str = Field(..., min_length=1)
    detail: dict[str, float | str] | None = None


class ValidityReport(FrozenModel):
    """The aggregated findings from running checks over a plan.

    Findings are held as a tuple (immutable). The query properties are read-only helpers
    the composition logic uses; they encode no policy themselves.
    """

    findings: tuple[Finding, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not self.findings

    @property
    def has_blocking(self) -> bool:
        return any(f.severity is Severity.BLOCKING for f in self.findings)

    @property
    def has_modifiable(self) -> bool:
        return any(f.severity is Severity.MODIFIABLE for f in self.findings)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)


class CheckContext(FrozenModel):
    """Read-only inputs handed to every validity check.

    Pre-seeded with the plan and its already-computed cost estimate, so checks never
    re-estimate. Frozen, so a check cannot swap out or mutate what it was given.

    Extensible by design: future checks add what they need here (e.g. M5 will add lazy
    access to a loaded USD stage - see ADR 0004). Not added until a check needs it.
    """

    plan: GenerationPlan
    cost_estimate: CostEstimate
