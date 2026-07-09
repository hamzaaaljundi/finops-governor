"""Scripted fake planner model (M6, Task 6.2).

The CI-testable stand-in for a real language model. It returns pre-scripted responses in
order and records every prompt it receives, which lets tests assert two things a live
model never could deterministically:

  * the repair loop's behavior on specific failures (malformed JSON, schema violations,
    then success) - by scripting exactly that sequence;
  * that repair prompts actually contain the validation error text - by inspecting the
    recorded prompts.

Calling it more times than it has scripted responses raises immediately: in tests, an
unexpected extra model call is a bug, not something to paper over.
"""


class FakePlannerModel:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if len(self.prompts) > len(self._responses):
            raise AssertionError(
                f"FakePlannerModel exhausted: {len(self._responses)} responses "
                f"scripted, call #{len(self.prompts)} received."
            )
        return self._responses[len(self.prompts) - 1]
