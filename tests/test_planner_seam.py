"""Planner seam tests (M6, Task 6.2)."""

import pytest

from finops_governor.planner import FakePlannerModel, PlannerModel


def test_fake_conforms_to_interface():
    assert isinstance(FakePlannerModel(responses=[]), PlannerModel)


def test_any_conforming_object_satisfies_the_interface():
    class Trivial:
        def complete(self, prompt: str) -> str:
            return "{}"

    assert isinstance(Trivial(), PlannerModel)


def test_returns_scripted_responses_in_order():
    fake = FakePlannerModel(responses=["first", "second"])
    assert fake.complete("p1") == "first"
    assert fake.complete("p2") == "second"


def test_records_prompts_for_inspection():
    fake = FakePlannerModel(responses=["a", "b"])
    fake.complete("hello")
    fake.complete("hello again, with error feedback")
    assert fake.prompts == ["hello", "hello again, with error feedback"]
    assert fake.calls == 2


def test_exhaustion_raises_loudly():
    fake = FakePlannerModel(responses=["only one"])
    fake.complete("p1")
    with pytest.raises(AssertionError, match="exhausted"):
        fake.complete("p2")
