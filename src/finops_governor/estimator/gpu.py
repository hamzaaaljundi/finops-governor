"""GPU render cost model (M2, Task 2.3).

The first concrete CostModel: the affine, per-modality, deterministic estimator for GPU
path-tracing / rasterization workloads, parameterized by a HardwareProfile. Implements
the formula specified in docs/cost-model.md (sections 3 and 4).

Deliberately pre-execution and deterministic: same plan + same profile -> same estimate.
It does NOT model VRAM residency, cache state, or per-frame variance (see cost-model.md
section 7) because those are unknowable before execution.
"""

from finops_governor.estimator.estimate import CostEstimate, SceneCost
from finops_governor.estimator.profiles import HardwareProfile
from finops_governor.schemas import GenerationPlan
from finops_governor.schemas.models import (
    OutputModality,
    RenderSettings,
    RendererType,
)

SECONDS_PER_HOUR = 3600

# Per-modality cost weights (docs/cost-model.md section 4). Substrate physics, not
# per-device pricing, so they live with the GPU model rather than in a HardwareProfile.
MODALITY_WEIGHTS: dict[OutputModality, float] = {
    OutputModality.RGB: 1.00,
    OutputModality.DEPTH: 0.15,
    OutputModality.SURFACE_NORMALS: 0.15,
    OutputModality.SEMANTIC_SEGMENTATION: 0.02,
    OutputModality.INSTANCE_SEGMENTATION: 0.02,
    OutputModality.BBOX_2D: 0.02,
    OutputModality.BBOX_3D: 0.02,
    OutputModality.POSE: 0.02,
}


class GpuRenderCostModel:
    """Estimate GPU render cost for a plan on a given hardware profile."""

    def __init__(self, profile: HardwareProfile) -> None:
        self.profile = profile

    def _base_render_seconds(self, rs: RenderSettings) -> float:
        pixel_ratio = (rs.width * rs.height) / self.profile.ref_pixels
        if rs.renderer == RendererType.RASTERIZED:
            return self.profile.rasterize_factor * pixel_ratio
        sample_ratio = rs.samples_per_pixel / self.profile.ref_samples
        return self.profile.ref_render_seconds * pixel_ratio * sample_ratio

    def _modality_factor(self, modalities: list[OutputModality]) -> float:
        return sum(MODALITY_WEIGHTS[m] for m in modalities)

    def estimate(self, plan: GenerationPlan) -> CostEstimate:
        p = self.profile
        per_image_s = self._base_render_seconds(plan.render_settings) * self._modality_factor(
            plan.modalities
        )

        per_scene: list[SceneCost] = []
        total_images = 0
        total_hours = 0.0
        total_usd = 0.0

        for scene in plan.scenes:
            images = scene.variation_count * len(scene.cameras)
            fixed_s = p.fixed_ingestion_seconds
            render_s = images * per_image_s
            scene_total_s = (fixed_s + render_s) * p.contingency_factor
            scene_hours = scene_total_s / SECONDS_PER_HOUR
            scene_usd = scene_hours * p.price_per_hour_usd

            per_scene.append(
                SceneCost(
                    scene_id=scene.scene_id,
                    images=images,
                    fixed_seconds=fixed_s,
                    render_seconds=render_s,
                    subtotal_usd=scene_usd,
                )
            )
            total_images += images
            total_hours += scene_hours
            total_usd += scene_usd

        return CostEstimate(
            total_usd=total_usd,
            total_gpu_hours=total_hours,
            total_images=total_images,
            hardware_profile=p.name,
            per_scene=per_scene,
        )
