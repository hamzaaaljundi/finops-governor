"""Hardware profiles (M2, Task 2.2).

Loads the hardware profile data (per-device pricing and render constants) that the
GPU cost model is parameterized by. Keeping these as data — not hardcoded constants —
is what makes the estimator multi-device: adding a GPU is a new JSON entry, not a code
change.

Each profile is validated on load via a StrictModel, so a typo or unknown key in the
data file fails loudly instead of silently producing a wrong cost.
"""

import json
from importlib import resources

from pydantic import Field

from finops_governor.schemas.models import StrictModel

_DATA_PACKAGE = "finops_governor.estimator"
_DATA_FILE = "data/hardware_profiles.json"

DEFAULT_PROFILE_ID = "a10g"


class HardwareProfile(StrictModel):
    """Per-device cost constants. All fields are static; nothing runtime-dependent.

    See docs/cost-model.md for the meaning of each field and the formula that
    consumes them.
    """

    name: str = Field(..., min_length=1)
    price_per_hour_usd: float = Field(..., gt=0)
    ref_render_seconds: float = Field(..., gt=0)
    ref_pixels: int = Field(..., gt=0)
    ref_samples: int = Field(..., gt=0)
    rasterize_factor: float = Field(..., gt=0)
    fixed_ingestion_seconds: float = Field(..., ge=0)
    # Extra per-scene ingestion when annotation modifiers are active (session-3
    # measurement: r4 53.18s vs r1 38.46s on the A10G). Defaults to 0.0 for
    # profiles where it has not been measured; omitted from their JSON entries.
    annot_ingestion_extra_seconds: float = Field(0.0, ge=0)
    contingency_factor: float = Field(..., ge=1)  # overhead never reduces cost
    vram_gb: int = Field(..., gt=0)


def load_profiles() -> dict[str, HardwareProfile]:
    """Load and validate every hardware profile from the bundled data file."""
    raw = resources.files(_DATA_PACKAGE).joinpath(_DATA_FILE).read_text(encoding="utf-8")
    data = json.loads(raw)
    return {key: HardwareProfile.model_validate(value) for key, value in data.items()}


def get_profile(profile_id: str) -> HardwareProfile:
    """Return one profile by id, with a helpful error listing valid ids."""
    profiles = load_profiles()
    try:
        return profiles[profile_id]
    except KeyError:
        valid = ", ".join(sorted(profiles))
        raise KeyError(f"Unknown hardware profile '{profile_id}'. Available: {valid}.") from None


def get_default_profile() -> HardwareProfile:
    """Return the default profile used when a caller does not specify one."""
    return get_profile(DEFAULT_PROFILE_ID)
