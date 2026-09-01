"""Plan schema — full model set (M1, Tasks 1.3–1.5, extended for diversity gating).

Bottom-up construction: leaf value objects first, then the composite Scene, then the
top-level GenerationPlan that the whole system passes around.

All plan models inherit from StrictModel so unknown fields are rejected rather than
silently dropped — making the schema a hard boundary between the fuzzy world (the
LLM planner) and the deterministic world (cost estimator + gates).

Validation is layered by responsibility:
  * Field-level constraints guard individual values.
  * model_validator(mode="after") guards cross-field / whole-object consistency, and
    lives on the model that *owns* the data it checks.

Budget affordability, geometric plausibility, and training-value (diversity) are NOT
checked here — those are the gates' jobs. The schema validates shape and internal
consistency only.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base for all plan schemas.

    Rejects unknown fields (extra="forbid") so malformed plans fail validation instead
    of silently losing data.
    """

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class OutputModality(str, Enum):
    """A ground-truth output captured per rendered image."""

    RGB = "RGB"
    DEPTH = "DEPTH"
    SEMANTIC_SEGMENTATION = "SEMANTIC_SEGMENTATION"
    INSTANCE_SEGMENTATION = "INSTANCE_SEGMENTATION"
    BBOX_2D = "BBOX_2D"
    BBOX_3D = "BBOX_3D"
    SURFACE_NORMALS = "SURFACE_NORMALS"
    POSE = "POSE"


class RendererType(str, Enum):
    """Rendering backend. Path tracing trades cost for physical accuracy."""

    PATH_TRACED = "PATH_TRACED"
    RASTERIZED = "RASTERIZED"


# --------------------------------------------------------------------------- #
# Leaf models
# --------------------------------------------------------------------------- #


class Transform(StrictModel):
    """A placement in 3D space. Reused by assets and cameras.

    Rotation is Euler angles in degrees (readable for hand-authored fixtures).
    """

    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)  # Euler degrees
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @field_validator("scale")
    @classmethod
    def validate_scale(cls, v: tuple[float, float, float]) -> tuple[float, float, float]:
        if any(s <= 0 for s in v):
            raise ValueError("All scale components must be strictly greater than 0.")
        return v


class AssetReference(StrictModel):
    """A pointer to a USD asset plus where it sits in the scene."""

    asset_id: str = Field(..., min_length=1)
    usd_path: str = Field(..., min_length=1)
    transform: Transform = Field(default_factory=Transform)
    category: str | None = None

    @field_validator("usd_path")
    @classmethod
    def validate_usd_extension(cls, v: str) -> str:
        if not v.endswith((".usd", ".usda", ".usdc")):
            raise ValueError("usd_path must end with .usd, .usda, or .usdc")
        return v


class Camera(StrictModel):
    """A viewpoint. Camera count is a direct image-count (and cost) multiplier."""

    camera_id: str = Field(..., min_length=1)
    transform: Transform
    fov_degrees: float = Field(50.0, gt=0, lt=180)


class RenderSettings(StrictModel):
    """Quality/size knobs — the main per-image cost drivers."""

    width: int = Field(..., gt=0, le=8192)
    height: int = Field(..., gt=0, le=8192)
    samples_per_pixel: int = Field(64, gt=0, le=1024)
    renderer: RendererType = RendererType.PATH_TRACED

    @model_validator(mode="after")
    def check_renderer_sample_consistency(self) -> "RenderSettings":
        if self.renderer == RendererType.RASTERIZED and self.samples_per_pixel > 1:
            raise ValueError(
                "RASTERIZED renderer does not use samples_per_pixel; "
                "set samples_per_pixel=1 or use the PATH_TRACED renderer."
            )
        return self


class Budget(StrictModel):
    """The spend constraint the budget gate enforces. Carries the ceiling only."""

    max_usd: float = Field(..., gt=0)
    currency: str = "USD"


# --------------------------------------------------------------------------- #
# Domain-randomization declaration (consumed by the diversity gate, M4)
# --------------------------------------------------------------------------- #


class RandomizationParameter(StrictModel):
    """One domain-randomization axis: which quantity varies and how densely.

    `levels` is the number of distinct values sampled along this axis (works for both
    continuous and discrete parameters). It is what the diversity gate uses to estimate
    coverage capacity vs. the number of variations. `min_value`/`max_value` optionally
    record a continuous range for future domain-gap checks; they do not affect the v1
    diversity proxy.
    """

    name: str = Field(..., min_length=1)
    levels: int = Field(..., ge=1)
    min_value: float | None = None
    max_value: float | None = None

    @model_validator(mode="after")
    def check_range(self) -> "RandomizationParameter":
        if self.min_value is not None and self.max_value is not None:
            if self.min_value >= self.max_value:
                raise ValueError("min_value must be less than max_value.")
        return self


class Randomization(StrictModel):
    """Declared domain randomization for a scene: which parameters vary and how densely.

    Optional on a Scene. When present, the diversity gate (M4) uses it to estimate how
    much of a job's variation budget lands in already-covered regions of the parameter
    space — i.e. predictable low training value — before any GPU spend.
    """

    parameters: list[RandomizationParameter] = Field(..., min_length=1)

    @model_validator(mode="after")
    def check_unique_parameter_names(self) -> "Randomization":
        names = [p.name for p in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("randomization parameter names must be unique.")
        return self


# --------------------------------------------------------------------------- #
# Composite model
# --------------------------------------------------------------------------- #


class Scene(StrictModel):
    """One 3D setup and how many randomized variations of it to produce.

    A Scene owns its assets and cameras, so it guarantees their IDs are unique.
    `randomization` optionally declares what varies across the variations.
    """

    scene_id: str = Field(..., min_length=1)
    environment: AssetReference
    assets: list[AssetReference] = Field(..., min_length=1)
    cameras: list[Camera] = Field(..., min_length=1)
    variation_count: int = Field(..., ge=1)
    randomization: Randomization | None = None

    @model_validator(mode="after")
    def check_unique_child_ids(self) -> "Scene":
        asset_ids = [a.asset_id for a in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError(f"Duplicate asset_id found in scene '{self.scene_id}'.")

        camera_ids = [c.camera_id for c in self.cameras]
        if len(camera_ids) != len(set(camera_ids)):
            raise ValueError(f"Duplicate camera_id found in scene '{self.scene_id}'.")
        return self


# --------------------------------------------------------------------------- #
# Top-level model
# --------------------------------------------------------------------------- #


class GenerationPlan(StrictModel):
    """The object the whole system passes around: a job plus its budget."""

    plan_id: str = Field(..., min_length=1)
    request_text: str | None = None
    scenes: list[Scene] = Field(..., min_length=1)
    modalities: list[OutputModality] = Field(..., min_length=1)
    render_settings: RenderSettings
    budget: Budget
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # v2.0-energy: carbon-aware urgency class (docs/energy-model.md section 2).
    urgency: str = Field("standard", pattern="^(interactive|standard|deferrable)$")
    # Reclassification audit trail: a planner may PROPOSE deferrable->interactive,
    # but the gate BLOCKs it unless a human resubmits with approved_reclass=True
    # (CLI: --approve-reclass). Deterministic, audit-visible in the saved plan.
    urgency_reclassified_from: str | None = None
    approved_reclass: bool = False

    @field_validator("modalities")
    @classmethod
    def prevent_duplicate_modalities(cls, v: list[OutputModality]) -> list[OutputModality]:
        if len(v) != len(set(v)):
            raise ValueError("modalities cannot contain duplicates.")
        return v

    @field_validator("scenes")
    @classmethod
    def prevent_duplicate_scene_ids(cls, v: list[Scene]) -> list[Scene]:
        scene_ids = [s.scene_id for s in v]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("Every scene_id in the plan must be unique.")
        return v
