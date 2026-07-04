"""Validity check interface (M3, Task 3.1).

The generic seam of the multi-axis gate. Anything that examines a plan and returns
findings is a ValidityCheck; the gate depends on THIS, never on a concrete check. Cost
(Task 3.2), diversity (M4), and USD geometry (M5) are all implementations of this one
interface.

Implementations MUST be pure reads: given the frozen CheckContext, return findings and
mutate nothing.
"""

from typing import Protocol, runtime_checkable

from finops_governor.validity.models import CheckContext, Finding


@runtime_checkable
class ValidityCheck(Protocol):
    name: str

    def check(self, context: CheckContext) -> list[Finding]: ...
