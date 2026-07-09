"""Planner model interface (M6, Task 6.2).

The seam between the planner's deterministic logic (prompting, validation, bounded
repair - Task 6.3) and any actual language model. The planner depends on THIS, never on
a vendor SDK.

Fourth use of the project's pluggable-seam pattern (CostModel, ValidityCheck,
UsdStageLoader isolation, now PlannerModel): one live implementation (the Anthropic
client, Task 6.4) and one fake for tests (fake.py), so every planner code path runs in
CI without network access or API keys.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlannerModel(Protocol):
    def complete(self, prompt: str) -> str:
        """Return the model's raw text response to the prompt."""
        ...
