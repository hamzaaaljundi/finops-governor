"""Plan schema — full model set (M1, Tasks 1.3–1.5).

Bottom-up construction: leaf value objects first, then the composite Scene, then the
top-level GenerationPlan that the whole system passes around.

All plan models inherit from StrictModel so unknown fields are rejected rather than
silently dropped — making the schema a hard boundary between the fuzzy world (the
LLM planner, M4) and the deterministic world (cost estimator + gates, M2/M3): a
malformed plan fails loudly instead of constructing a plausible-looking object.

Validation is layered by responsibility:
  * Field-level constraints (Field(gt=...), min_length, single-field field_validators)
    guard individual values.
  * model_validator(mode="after") guards cross-field / whole-object consistency, and
    lives on the model that *owns* the data it checks (a Scene guarantees its own
    asset/camera IDs are unique; the plan guarantees scene IDs are unique).

Budget affordability (M2) and geometric plausibility (M3) are deliberately NOT checked
here — those are the gates' jobs. The schema validates shape and internal consistency,
not cost or physics.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base for all plan schemas.

    Rejects unknown fields (extra="forbid") so malformed plans — e.g. an LLM that
    emits a hallucinated or misspelled field — fail validation instead of silently
    losing data.
    """

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Enums (not Pydantic models — extra="forbid" does not apply to them)
# --------------------------------------------------------------------------- #


class OutputModality(str, Enum):
    """A ground-truth output captured per rendered image.

    Each additional modality adds render/annotation cost — the concrete expression
    of the project's multimodal framing.
    """

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

    Rotation is expressed as Euler angles in degrees (decision #1: readable for
    hand-authored fixtures; gimbal-lock edge cases accepted and documented).
    """

    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)  # Euler degrees
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @field_validator("scale")
    @classmethod
    def validate_scale(
        cls, v: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        if any(s <= 0 for s in v):
            raise ValueError("All scale components must be strictly greater than 0.")
        return v


class AssetReference(StrictModel):
    """A pointer to a USD asset plus where it sits in the scene.

    The validity gate (M3) loads geometry from usd_path and uses transform for
    bounds/collision checks; asset_id identifies instances for segmentation and
    produces readable validation errors.
    """

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
    """Quality/size knobs — the main per-image cost drivers.

    samples_per_pixel is a major cost driver for path tracing.
    """

    width: int = Field(..., gt=0, le=8192)
    height: int = Field(..., gt=0, le=8192)
    samples_per_pixel: int = Field(64, gt=0, le=1024)
    renderer: RendererType = RendererType.PATH_TRACED

    @model_validator(mode="after")
    def check_renderer_sample_consistency(self) -> "RenderSettings":
        # samples_per_pixel is a path-tracing concept. A rasterized render with more
        # than one sample is contradictory, so we flag it loudly rather than silently
        # normalize — surfacing the contradiction fits a governor whose whole purpose
        # is correctness and auditability (spec Section 7). Rasterized callers must
        # set samples_per_pixel=1 explicitly.
        if self.renderer == RendererType.RASTERIZED and self.samples_per_pixel > 1:
            raise ValueError(
                "RASTERIZED renderer does not use samples_per_pixel; "
                "set samples_per_pixel=1 or use the PATH_TRACED renderer."
            )
        return self


class Budget(StrictModel):
    """The spend constraint the budget gate (M2) enforces.

    Carries the ceiling only — never the estimate, which M2 computes from the plan.
    """

    max_usd: float = Field(..., gt=0)
    currency: str = "USD"


# --------------------------------------------------------------------------- #
# Composite model
# --------------------------------------------------------------------------- #


class Scene(StrictModel):
    """One 3D setup and how many randomized variations of it to produce.

    A Scene owns its assets and cameras, so it is responsible for guaranteeing their
    IDs are internally unique — validation lives here, not at the plan level.
    """

    scene_id: str = Field(..., min_length=1)
    environment: AssetReference
    assets: list[AssetReference] = Field(..., min_length=1)
    cameras: list[Camera] = Field(..., min_length=1)
    variation_count: int = Field(..., ge=1)

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
    """The object the whole system passes around: a job to be done plus its budget.

    Kept dumb — it holds structure, not behavior. Gates decide verdicts; the estimator
    computes cost; the plan only describes the job.
    """

    plan_id: str = Field(..., min_length=1)
    request_text: str | None = None
    scenes: list[Scene] = Field(..., min_length=1)
    modalities: list[OutputModality] = Field(..., min_length=1)
    render_settings: RenderSettings
    budget: Budget
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("modalities")
    @classmethod
    def prevent_duplicate_modalities(
        cls, v: list[OutputModality]
    ) -> list[OutputModality]:
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
