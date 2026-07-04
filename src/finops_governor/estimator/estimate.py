"""Cost estimate output types (M2, Task 2.3).

The result a CostModel produces. Rich, not a bare float: the per-scene breakdown is
what lets the modify logic (2.6) target a specific scene and what makes the audit
trail legible (M5). All fields are raw (unrounded) so downstream math stays exact;
round only for display.
"""

from finops_governor.schemas.models import StrictModel


class SceneCost(StrictModel):
    """Per-scene cost breakdown.

    render_seconds is the variable render time (images x per-image cost); fixed_seconds
    is the per-scene ingestion overhead. subtotal_usd already includes the contingency
    multiplier and price, so per-scene subtotals sum to CostEstimate.total_usd.
    """

    scene_id: str
    images: int
    fixed_seconds: float
    render_seconds: float
    subtotal_usd: float


class CostEstimate(StrictModel):
    """The estimated cost of a plan on a specific hardware profile."""

    total_usd: float
    total_gpu_hours: float
    total_images: int
    hardware_profile: str
    per_scene: list[SceneCost]
