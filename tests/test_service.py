"""HTTP service tests (M8, Task 8.3) - every row of the status-code table
(docs/service-model.md, section 3), driven by TestClient with the scripted fake."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finops_governor.planner import FakePlannerModel
from finops_governor.service import create_app

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures"


def _plan_dict(budget: float = 50.0, variation_count: int = 10, levels=None) -> dict:
    scene = {
        "scene_id": "s1",
        "environment": {"asset_id": "e", "usd_path": "e.usda"},
        "assets": [{"asset_id": "a", "usd_path": "a.usda"}],
        "cameras": [{"camera_id": "c", "transform": {}}],
        "variation_count": variation_count,
    }
    if levels:
        scene["randomization"] = {
            "parameters": [{"name": f"p{i}", "levels": v} for i, v in enumerate(levels)]
        }
    return {
        "plan_id": "p1",
        "scenes": [scene],
        "modalities": ["RGB"],
        "render_settings": {"width": 1280, "height": 720},
        "budget": {"max_usd": budget},
    }


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


# --- liveness + discoverability ---


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_profiles_lists_the_hardware_data(client):
    body = client.get("/profiles").json()
    assert set(body) >= {"t4", "a10g", "h100"}
    assert body["a10g"]["price_per_hour_usd"] == 1.006


# --- /evaluate: verdicts are 200s ---


def test_evaluate_approve(client):
    r = client.post("/evaluate", json=_plan_dict())
    assert r.status_code == 200
    assert r.json()["verdict"] == "APPROVE"


def test_evaluate_block_is_200(client):
    r = client.post("/evaluate", json=_plan_dict(budget=0.000001))
    assert r.status_code == 200  # the gate WORKING, not a transport error
    assert r.json()["verdict"] == "BLOCK"


def test_evaluate_modify_carries_the_proposal(client):
    r = client.post("/evaluate", json=_plan_dict(variation_count=50_000, levels=[4, 4]))
    body = r.json()
    assert body["verdict"] == "MODIFY"
    assert body["modified_plan"]["scenes"][0]["variation_count"] == 26
    assert any(m.startswith("value:") for m in body["modifications"])


def test_evaluate_geometry_flag_blocks_a_broken_stage(client):
    scenario = json.loads((FIXTURES / "geometry" / "floor_clip_scene.json").read_text())
    for scene in scenario["scenes"]:
        scene["environment"]["usd_path"] = str(REPO / scene["environment"]["usd_path"])
        for asset in scene["assets"]:
            asset["usd_path"] = str(REPO / asset["usd_path"])
    r = client.post("/evaluate?geometry=true", json=scenario)
    assert r.status_code == 200
    assert r.json()["verdict"] == "BLOCK"
    assert "usd_geometry" in r.json()["reason"]


# --- the error rows ---


def test_invalid_plan_is_422(client):
    r = client.post("/evaluate", json={"plan_id": "x"})
    assert r.status_code == 422


def test_unknown_profile_is_400(client):
    r = client.post("/evaluate?profile=tpu9", json=_plan_dict())
    assert r.status_code == 400
    assert "unknown hardware profile" in r.json()["detail"]


def test_unreachable_model_is_502(monkeypatch):
    # no injected model AND no key: construction succeeds, the call fails cleanly.
    # deleting the key guarantees this test can never make a live call.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = TestClient(create_app())
    r = client.post("/pipeline", json={"request": "req", "budget_usd": 50.0})
    assert r.status_code == 502
    assert "model call failed" in r.json()["detail"]


# --- /advise ---


def test_advise_recommends_the_cheapest(client):
    plan = json.loads((FIXTURES / "plans" / "valid" / "multi_scene.json").read_text())
    body = client.post("/advise", json=plan).json()
    assert body["recommended_profile_id"] == "a10g"
    assert [r["profile_id"] for r in body["ranking"]] == ["a10g", "h100", "t4"]


# --- /pipeline: terminal states are 200s, the trail is the response ---


def test_pipeline_executes_and_returns_the_trail():
    fake = FakePlannerModel([json.dumps(_plan_dict(variation_count=50_000, levels=[4, 4]))])
    client = TestClient(create_app(planner_model=fake))
    r = client.post("/pipeline", json={"request": "50k arm variations", "budget_usd": 1000.0})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "EXECUTED"
    assert [e["node"] for e in body["events"]] == [
        "plan",
        "gate",
        "adopt",
        "gate",
        "execute",
    ]
    assert body["events"][1]["driving_axes"] == ["diversity"]
    assert body["plan"]["scenes"][0]["variation_count"] == 26


def test_pipeline_blocked_is_200():
    fake = FakePlannerModel([json.dumps(_plan_dict(budget=0.000001))])
    client = TestClient(create_app(planner_model=fake))
    r = client.post("/pipeline", json={"request": "impossible", "budget_usd": 0.000001})
    assert r.status_code == 200
    assert r.json()["status"] == "BLOCKED"


def test_pipeline_planner_exhaustion_is_200_failed():
    fake = FakePlannerModel(["bad", "bad", "bad"])
    client = TestClient(create_app(planner_model=fake))
    r = client.post("/pipeline", json={"request": "req", "budget_usd": 50.0})
    assert r.status_code == 200  # the pipeline RAN; the trail is the deliverable
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["error"] is not None
    assert body["events"][-1]["node"] == "plan"


# --- /portfolio: one shared budget across N jobs (M10, ADR 0010) ---


def test_portfolio_allocates_and_is_200(client):
    plan_a = _plan_dict(budget=1_000_000, variation_count=500, levels=[20, 20])
    plan_a["plan_id"] = "job-A"
    plan_b = _plan_dict(budget=1_000_000, variation_count=500, levels=[5])
    plan_b["plan_id"] = "job-B"
    r = client.post("/portfolio", json={"plans": [plan_a, plan_b], "budget_usd": 0.2})
    assert r.status_code == 200
    body = r.json()
    assert body["budget_usd"] == 0.2
    assert body["total_cost_usd"] <= 0.2
    assert {j["plan_id"] for j in body["jobs"]} == {"job-A", "job-B"}


def test_portfolio_excluded_job_is_still_200(client):
    """An excluded (BLOCKED) job is the allocator working, not a transport error -
    same transaction-vs-verdict rule as every other endpoint."""
    fundable = _plan_dict(budget=1_000_000, variation_count=10)
    fundable["plan_id"] = "ok"
    doomed = _plan_dict(budget=0.000001, variation_count=100_000)  # unrecoverable
    doomed["plan_id"] = "doomed"
    r = client.post("/portfolio", json={"plans": [fundable, doomed], "budget_usd": 5.0})
    assert r.status_code == 200
    by_id = {j["plan_id"]: j for j in r.json()["jobs"]}
    assert by_id["ok"]["included"]
    assert not by_id["doomed"]["included"]
    assert "BLOCKING" in by_id["doomed"]["reason"]


def test_portfolio_multi_scene_job_is_400(client):
    """A multi-scene plan violates the ADR 0010 decision-7 v1 contract - a request
    error (400), not a verdict."""
    plan = _plan_dict(budget=1_000_000)
    plan["scenes"].append({**plan["scenes"][0], "scene_id": "s2"})
    r = client.post("/portfolio", json={"plans": [plan], "budget_usd": 5.0})
    assert r.status_code == 400
    assert "exactly one scene" in r.json()["detail"]


def test_portfolio_unknown_profile_is_400(client):
    r = client.post(
        "/portfolio",
        json={"plans": [_plan_dict()], "budget_usd": 5.0, "profile": "tpu9"},
    )
    assert r.status_code == 400
    assert "unknown hardware profile" in r.json()["detail"]


def test_portfolio_empty_plan_list_is_422(client):
    """Pydantic contract: at least one plan (min_length=1) - a malformed request."""
    r = client.post("/portfolio", json={"plans": [], "budget_usd": 5.0})
    assert r.status_code == 422
