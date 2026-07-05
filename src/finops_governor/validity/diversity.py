"""Diversity / redundancy validity check (M4, Task 4.2).

The project's headline axis. Estimates, before any GPU spend, how much of a job's
variation budget lands in already-covered parameter space - i.e. predictable low
training-value - by reasoning over the declared randomization (never over generated data).

For each scene that declares randomization:
    capacity           = product of per-parameter `levels`   (distinct configurations)
    redundancy_ratio   = variation_count / capacity          (avg samples per config)
    redundant_fraction = 1 - capacity / variation_count      (share beyond first coverage)
    estimated_wasted   = scene_subtotal_usd * redundant_fraction

A WARNING fires when redundancy_ratio exceeds the threshold (default 2.0). Scenes without
declared randomization are skipped - the check refuses to judge undeclared coverage.

See docs/diversity-model.md for the proxy's assumptions and its documented limits.
"""

from finops_governor.validity.models import CheckContext, Finding, Severity

_DEFAULT_REDUNDANCY_THRESHOLD = 2.0


class DiversityCheck:
    name = "diversity"

    def __init__(
        self, redundancy_threshold: float = _DEFAULT_REDUNDANCY_THRESHOLD
    ) -> None:
        self._threshold = redundancy_threshold

    def check(self, context: CheckContext) -> list[Finding]:
        cost_by_scene = {
            sc.scene_id: sc.subtotal_usd for sc in context.cost_estimate.per_scene
        }

        findings: list[Finding] = []
        for scene in context.plan.scenes:
            if scene.randomization is None:
                continue  # cannot judge coverage that was never declared

            capacity = 1
            for param in scene.randomization.parameters:
                capacity *= param.levels

            variations = scene.variation_count
            redundancy_ratio = variations / capacity
            if redundancy_ratio <= self._threshold:
                continue

            redundant_fraction = 1 - capacity / variations
            wasted = cost_by_scene.get(scene.scene_id, 0.0) * redundant_fraction

            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.WARNING,
                    reason=(
                        f"scene '{scene.scene_id}': {variations} variations across "
                        f"~{capacity} declared configurations "
                        f"(~{redundancy_ratio:.0f}x oversampled, "
                        f"~{redundant_fraction * 100:.0f}% redundant); est. "
                        f"${wasted:.2f} of spend adds little training value."
                    ),
                    detail={
                        "variations": float(variations),
                        "capacity": float(capacity),
                        "redundancy_ratio": round(redundancy_ratio, 2),
                        "redundant_fraction": round(redundant_fraction, 4),
                        "estimated_wasted_usd": round(wasted, 2),
                    },
                )
            )
        return findings
