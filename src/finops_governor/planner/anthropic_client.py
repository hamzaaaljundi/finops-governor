"""Live Anthropic client behind the PlannerModel seam (M6, Task 6.4).

The thin real implementation - deliberately minimal, because this is the one sliver of
the planner that cannot run in CI (it needs a network and an API key). Everything
interesting (prompting, validation, the repair loop) lives in core.py, where the
scripted fake covers every path.

Configuration:
  * API key: passed explicitly, or resolved by the SDK from the ANTHROPIC_API_KEY
    environment variable.
  * Model: constructor argument (default below) so a model change is one argument,
    not a code change.
  * Temperature 0 per the locked design decision (docs/planner-model.md, decision 5):
    reduces variance; determinism still lives in the gate, not the planner.

The `anthropic` import is deferred into the constructor so that importing the planner
package never requires the SDK unless the live client is actually used.
"""

from finops_governor.planner.base import PlannerModel

_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_MAX_TOKENS = 4096


class AnthropicPlannerModel:
    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = 0.0,
        api_key: str | None = None,
    ) -> None:
        from anthropic import Anthropic  # deferred: only the live client needs the SDK

        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def complete(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


# Static conformance note: AnthropicPlannerModel satisfies PlannerModel structurally;
# the test suite asserts it via isinstance (runtime_checkable Protocol).
_: type[PlannerModel] = AnthropicPlannerModel
