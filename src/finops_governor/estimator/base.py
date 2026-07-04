"""The CostModel interface (M2, Task 2.3).

The generic seam of the governor. Anything that turns a plan into a CostEstimate is a
valid CostModel; the gate depends on THIS, never on a concrete implementation. That
single indirection is what makes the governor substrate-agnostic: a CPU or TPU cost
model plugs in here without changing the gate.

Runtime-checkable so tests can assert an implementation satisfies the contract.
"""

from typing import Protocol, runtime_checkable

from finops_governor.estimator.estimate import CostEstimate
from finops_governor.schemas import GenerationPlan


@runtime_checkable
class CostModel(Protocol):
    def estimate(self, plan: GenerationPlan) -> CostEstimate: ...
