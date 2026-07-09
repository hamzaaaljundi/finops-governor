"""Diversity / redundancy validity check (M4; expected-coverage v2 and value-aware
severity in M6.5 - see ADR 0007).

The project's headline axis. Estimates, before any GPU spend, how much of a job's
variation budget is expected to land in already-covered parameter space - i.e.
predictable low training-value - by reasoning over the declared randomization (never
over generated data).

The model (uniform independent sampling, coupon-collector expectation):

    capacity           = product of per-parameter `levels`       (distinct configurations)
    expected_distinct  = capacity * (1 - (1 - 1/capacity)^n)     (n = variation_count)
    redundant_fraction = 1 - expected_distinct / n               (expected wasted share)
    estimated_wasted   = scene_subtotal_usd * redundant_fraction
    cost_per_distinct  = scene_subtotal_usd / expected_distinct

A finding fires when redundant_fraction exceeds the threshold (default 0.5) and is
**MODIFIABLE** (ADR 0007): redundancy above threshold is recoverable by construction -
redundant_fraction(1) = 0 for every capacity, so a compliant trim target always exists.
Each finding carries `justified_variation_count`, the largest count whose expected waste
is within the threshold; the Governor's value-trim pass reads it from there, keeping one
home for all coverage math.

Scenes without declared randomization are skipped - the check refuses to judge
undeclared coverage. See docs/diversity-model.md.
"""

from finops_governor.validity.models import CheckContext, Finding, Severity

_DEFAULT_WASTE_THRESHOLD = 0.5


def expected_distinct(variations: int, capacity: int) -> float:
    """Expected number of distinct configurations hit by `variations` uniform draws."""
    if capacity <= 0:
        return 0.0
    return capacity * (1.0 - (1.0 - 1.0 / capacity) ** variations)


def justified_variation_count(
    capacity: int, waste_threshold: float = _DEFAULT_WASTE_THRESHOLD
) -> int:
    """Largest variation count whose expected redundant fraction is within threshold.

    redundant_fraction is monotone non-decreasing in n (verified), so binary search.
    Always >= 1, since redundant_fraction(1) == 0 for every capacity.
    """
    if capacity <= 0:
        return 1

    def fraction(n: int) -> float:
        return 1.0 - expected_distinct(n, capacity) / n

    hi = 1
    while fraction(hi) <= waste_threshold:
        hi *= 2
    lo = max(1, hi // 2)
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if fraction(mid) <= waste_threshold:
            lo = mid
        else:
            hi = mid
    return lo


class DiversityCheck:
    name = "diversity"

    def __init__(self, waste_threshold: float = _DEFAULT_WASTE_THRESHOLD) -> None:
        self._threshold = waste_threshold

    def check(self, context: CheckContext) -> list[Finding]:
        cost_by_scene = {
            sc.scene_id: sc.subtotal_usd for sc in context.cost_estimate.per_scene
        }
        images_by_scene = {
            sc.scene_id: sc.images for sc in context.cost_estimate.per_scene
        }

        findings: list[Finding] = []
        for scene in context.plan.scenes:
            if scene.randomization is None:
                continue  # cannot judge coverage that was never declared

            capacity = 1
            for param in scene.randomization.parameters:
                capacity *= param.levels

            variations = scene.variation_count
            distinct = expected_distinct(variations, capacity)
            redundant_fraction = 1.0 - distinct / variations
            if redundant_fraction <= self._threshold:
                continue

            scene_usd = cost_by_scene.get(scene.scene_id, 0.0)
            wasted = scene_usd * redundant_fraction
            cost_per_distinct = scene_usd / distinct if distinct > 0 else 0.0
            images = images_by_scene.get(scene.scene_id, variations)
            nominal_per_image = scene_usd / images if images else 0.0
            justified = justified_variation_count(capacity, self._threshold)

            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.MODIFIABLE,
                    reason=(
                        f"scene '{scene.scene_id}': {variations} variations over "
                        f"~{capacity} declared configurations - expected "
                        f"~{redundant_fraction * 100:.0f}% redundant; est. "
                        f"${wasted:.2f} of spend adds little training value "
                        f"(effective ${cost_per_distinct:.2f}/distinct configuration "
                        f"vs ${nominal_per_image:.4f}/image nominal); recoverable by "
                        f"trimming to {justified} variations."
                    ),
                    detail={
                        "scene_id": scene.scene_id,
                        "variations": float(variations),
                        "capacity": float(capacity),
                        "expected_distinct": round(distinct, 1),
                        "redundancy_ratio": round(variations / capacity, 2),
                        "redundant_fraction": round(redundant_fraction, 4),
                        "estimated_wasted_usd": round(wasted, 2),
                        "effective_cost_per_distinct_usd": round(cost_per_distinct, 4),
                        "nominal_cost_per_image_usd": round(nominal_per_image, 4),
                        "justified_variation_count": float(justified),
                    },
                )
            )
        return findings
