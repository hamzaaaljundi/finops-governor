"""Diversity / redundancy validity check (M4, upgraded in M6.5 Task A).

The project's headline axis. Estimates, before any GPU spend, how much of a job's
variation budget is expected to land in already-covered parameter space - i.e.
predictable low training-value - by reasoning over the declared randomization (never
over generated data).

The v2 proxy models EXPECTED coverage under uniform independent sampling (the
coupon-collector expectation), not best-case spread:

    capacity           = product of per-parameter `levels`       (distinct configurations)
    expected_distinct  = capacity * (1 - (1 - 1/capacity)^n)     (n = variation_count)
    redundant_fraction = 1 - expected_distinct / n               (expected wasted share)
    estimated_wasted   = scene_subtotal_usd * redundant_fraction
    cost_per_distinct  = scene_subtotal_usd / expected_distinct  (effective unit price
                                                                  of training signal)

A WARNING fires when redundant_fraction exceeds the threshold (default 0.5: more than
half the scene's spend is expected redundant). This is smooth everywhere - a job
sampling 90 variations over 96 configurations reports its real ~35% expected collision
waste instead of the old model's zero. Scenes without declared randomization are
skipped - the check refuses to judge undeclared coverage.

See docs/diversity-model.md for the model, its assumptions, and its documented limits.
"""

from finops_governor.validity.models import CheckContext, Finding, Severity

_DEFAULT_WASTE_THRESHOLD = 0.5


def expected_distinct(variations: int, capacity: int) -> float:
    """Expected number of distinct configurations hit by `variations` uniform draws."""
    if capacity <= 0:
        return 0.0
    return capacity * (1.0 - (1.0 - 1.0 / capacity) ** variations)


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

            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    reason=(
                        f"scene '{scene.scene_id}': {variations} variations over "
                        f"~{capacity} declared configurations - expected "
                        f"~{redundant_fraction * 100:.0f}% redundant; est. "
                        f"${wasted:.2f} of spend adds little training value "
                        f"(effective ${cost_per_distinct:.2f}/distinct configuration "
                        f"vs ${nominal_per_image:.4f}/image nominal)."
                    ),
                    detail={
                        "variations": float(variations),
                        "capacity": float(capacity),
                        "expected_distinct": round(distinct, 1),
                        "redundancy_ratio": round(variations / capacity, 2),
                        "redundant_fraction": round(redundant_fraction, 4),
                        "estimated_wasted_usd": round(wasted, 2),
                        "effective_cost_per_distinct_usd": round(cost_per_distinct, 4),
                        "nominal_cost_per_image_usd": round(nominal_per_image, 4),
                    },
                )
            )
        return findings
