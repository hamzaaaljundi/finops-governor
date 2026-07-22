"""The HTTP service (M8, Task 8.3) - transport, not behavior.

A thin FastAPI skin over the Governor and the Orchestrator, transcribing
docs/service-model.md: the M1 GenerationPlan is /evaluate's request contract, the M7
PipelineState is /pipeline's response contract, and HTTP codes describe the transaction,
never the verdict (a BLOCK is the gate working: 200).

Run locally:

    uvicorn finops_governor.service:app --reload

Construction: `create_app(planner_model=...)` threads the planner seam through the
service layer so tests drive every endpoint with the scripted fake - no network, no
keys. Without an injected model, the live Anthropic client is constructed lazily on the
first /pipeline call (same deferred-SDK discipline as the CLI).
"""

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from finops_governor.advisor import ProfileAdvice, advise
from finops_governor.estimator import (
    GpuRenderCostModel,
    HardwareProfile,
    get_profile,
    load_profiles,
)
from finops_governor.gate.decision import GateDecision
from finops_governor.governor import Governor
from finops_governor.orchestration import Orchestrator, PipelineState
from finops_governor.planner import Planner, PlannerModel
from finops_governor.portfolio import PortfolioResult, allocate_portfolio
from finops_governor.schemas import GenerationPlan


class PipelineRequest(BaseModel):
    """The /pipeline request: a natural-language request under a budget ceiling."""

    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1)
    budget_usd: float = Field(gt=0)
    profile: str = "a10g"
    geometry: bool = False


class PortfolioRequest(BaseModel):
    """The /portfolio request: N single-scene candidate plans sharing one budget
    (M10, ADR 0010)."""

    model_config = ConfigDict(extra="forbid")

    plans: list[GenerationPlan] = Field(min_length=1)
    budget_usd: float = Field(gt=0)
    profile: str = "a10g"
    geometry: bool = False


def create_app(planner_model: PlannerModel | None = None) -> FastAPI:
    app = FastAPI(
        title="FinOps Governor",
        description=(
            "Deterministic pre-flight gate for synthetic-data GPU spend. "
            "HTTP codes describe the transaction, never the verdict: "
            "clients branch on `verdict` / `status` in the body."
        ),
        version="1.0.0",
    )
    _model_cache: list[PlannerModel] = [planner_model] if planner_model else []

    def _planner_model() -> PlannerModel:
        if not _model_cache:
            # Deferred: only the live /pipeline path needs the SDK (and a key).
            from finops_governor.planner import AnthropicPlannerModel

            _model_cache.append(AnthropicPlannerModel())
        return _model_cache[0]

    def _governor(profile_id: str, geometry: bool) -> Governor:
        try:
            profile = get_profile(profile_id)
        except KeyError:
            raise HTTPException(
                status_code=400, detail=f"unknown hardware profile: {profile_id}"
            ) from None
        cost_model = GpuRenderCostModel(profile)
        return (
            Governor.with_all_checks(cost_model)
            if geometry
            else Governor.with_default_checks(cost_model)
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/profiles")
    def profiles() -> dict[str, HardwareProfile]:
        return load_profiles()

    @app.post("/evaluate", response_model=GateDecision)
    def evaluate(
        plan: GenerationPlan,
        profile: str = Query(default="a10g"),
        geometry: bool = Query(default=False),
    ) -> GateDecision:
        """ONE gate pass: the gate's own interface (CLI evaluate mode over HTTP)."""
        return _governor(profile, geometry).evaluate(plan)

    @app.post("/advise", response_model=ProfileAdvice)
    def advise_endpoint(plan: GenerationPlan) -> ProfileAdvice:
        """Rank every hardware profile by this plan's cost; recommend the cheapest."""
        return advise(plan)

    @app.post("/portfolio", response_model=PortfolioResult)
    def portfolio(body: PortfolioRequest) -> PortfolioResult:
        """Allocate one shared budget across N single-scene jobs (M10, ADR 0010).

        Excluded/underfunded jobs are 200s - the allocation ran and the result is
        the deliverable, same transaction-vs-verdict rule as every other endpoint.
        400 is a contract violation the allocator itself names: a multi-scene plan
        (ADR 0010 decision 7 requires exactly one scene per job in v1).
        """
        try:
            profile = get_profile(body.profile)
        except KeyError:
            raise HTTPException(
                status_code=400, detail=f"unknown hardware profile: {body.profile}"
            ) from None
        cost_model = GpuRenderCostModel(profile)
        governor = _governor(body.profile, body.geometry)
        try:
            return allocate_portfolio(
                body.plans,
                budget_usd=body.budget_usd,
                cost_model=cost_model,
                governor=governor,
            )
        except ValueError as exc:  # the ADR 0010 decision-7 single-scene contract
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.post("/pipeline", response_model=PipelineState)
    def pipeline(body: PipelineRequest) -> PipelineState:
        """The full M7 pipeline; the response IS the audit trail.

        EXECUTED, BLOCKED, and FAILED (planner exhaustion) are all 200s - the
        pipeline ran and the trail is the deliverable. 502 is reserved for the
        upstream model being unreachable (missing key, network, auth).
        """
        governor = _governor(body.profile, body.geometry)
        orchestrator = Orchestrator(Planner(_planner_model()), governor)
        try:
            return orchestrator.run(body.request, budget_usd=body.budget_usd)
        except Exception as exc:  # SDK errors: missing key, network, auth
            raise HTTPException(
                status_code=502,
                detail=f"model call failed ({type(exc).__name__}): {exc}",
            ) from exc

    return app


app = create_app()
