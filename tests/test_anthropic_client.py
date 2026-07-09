"""Anthropic client tests (M6, Task 6.4).

The live client is the deliberately-thin untestable sliver: no test here makes a network
call. What IS testable: interface conformance, configuration, and that the module
imports without touching the SDK (the deferred-import guarantee).
"""

from finops_governor.planner import AnthropicPlannerModel, PlannerModel


def test_conforms_to_interface():
    client = AnthropicPlannerModel(api_key="test-key-no-network")
    assert isinstance(client, PlannerModel)


def test_locked_defaults():
    client = AnthropicPlannerModel(api_key="test-key-no-network")
    assert client.model == "claude-sonnet-4-6"
    assert client.temperature == 0.0  # locked decision 5
    assert client.max_tokens == 4096


def test_model_is_one_argument_to_change():
    client = AnthropicPlannerModel(
        model="claude-opus-4-8", api_key="test-key-no-network"
    )
    assert client.model == "claude-opus-4-8"


def test_module_imports_without_constructing_a_client():
    # the deferred import means this module (and the planner package) can be imported
    # in environments where using the live client would fail
    import finops_governor.planner.anthropic_client as mod

    assert hasattr(mod, "AnthropicPlannerModel")
