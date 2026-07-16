"""The profile advisor (M8, Task 8.2).

Answers the FinOps question the cost model has been able to answer since M2 but never
surfaced as a feature: **which hardware should this job run on?** The same plan through
the same estimator across every profile in hardware_profiles.json, ranked by total
cost - deterministic arithmetic, no new modeling.

The recurring punchline (docs/cost-model.md, section 6.3): the cost-optimal device is
frequently the mid-tier card, not the cheapest-per-hour (too slow) nor the fastest
(too expensive per hour). Surfacing that trade-off is exactly what a governor is for.
"""

from pydantic import BaseModel, ConfigDict

from finops_governor.estimator import GpuRenderCostModel, load_profiles
from finops_governor.schemas import GenerationPlan


class ProfileCost(BaseModel):
    """One profile's price for the job. Frozen and serializable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str
    profile_name: str
    price_per_hour_usd: float
    gpu_hours: float
    total_usd: float
    fits_budget: bool


class ProfileAdvice(BaseModel):
    """The full ranking, cheapest first. Frozen and serializable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str
    budget_usd: float
    ranking: tuple[ProfileCost, ...]
    recommended_profile_id: str
    max_savings_usd: float  # most expensive minus cheapest: the cost of picking wrong

    @property
    def recommended(self) -> ProfileCost:
        return self.ranking[0]


def advise(plan: GenerationPlan) -> ProfileAdvice:
    """Rank every hardware profile by this plan's total cost; recommend the cheapest."""
    rows = []
    for profile_id, profile in load_profiles().items():
        estimate = GpuRenderCostModel(profile).estimate(plan)
        rows.append(
            ProfileCost(
                profile_id=profile_id,
                profile_name=profile.name,
                price_per_hour_usd=profile.price_per_hour_usd,
                gpu_hours=round(estimate.total_gpu_hours, 4),
                total_usd=round(estimate.total_usd, 4),
                fits_budget=estimate.total_usd <= plan.budget.max_usd,
            )
        )
    rows.sort(key=lambda r: r.total_usd)
    return ProfileAdvice(
        plan_id=plan.plan_id,
        budget_usd=plan.budget.max_usd,
        ranking=tuple(rows),
        recommended_profile_id=rows[0].profile_id,
        max_savings_usd=round(rows[-1].total_usd - rows[0].total_usd, 4),
    )
