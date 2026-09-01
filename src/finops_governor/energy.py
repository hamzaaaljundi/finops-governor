"""Energy & carbon layer (v2.0-energy).

v1 governs what a synthetic-data job COSTS; this layer reports what it BURNS -
chained onto the same calibrated runtime term (`CostEstimate.total_gpu_hours`,
measured within 1.6% on real hardware, docs/calibration.md section 8) rather than
the guessed durations most energy estimates multiply TDP by.

The headline is not scheduling: it is that the M6.5 value-trim now carries a
carbon receipt. Every MODIFY that removes expected-redundant frames reports the
gCO2 those frames would have emitted - carbon reduced by NOT rendering data that
adds no training value. Deferral guidance is the second act: the gate emits
schedule ADVICE (recommended low-intensity window); it does not pretend to own a
scheduler (v1 has an execute stub, not a queue - honesty over theater).

Chain: kWh = tdp_kw x utilization x gpu_hours x PUE;  gCO2 = kWh x intensity.
utilization (default 0.75) and PUE (default 1.4) are documented assumptions -
docs/energy-model.md section 4 names both as the weakest terms and the
`nvidia-smi power.draw` calibration session that would convert utilization into
a measured constant.

Intensity sources sit behind a fake-able seam (same pattern as the planner's
model seam): `StaticIntensityCurves` ships 24-hour regional profiles derived from
public annual averages (sources in-line); a live API source is a drop-in.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from finops_governor.estimator.estimate import CostEstimate
from finops_governor.estimator.profiles import HardwareProfile

Urgency = Literal["interactive", "standard", "deferrable"]

DEFAULT_UTILIZATION = 0.75  # documented assumption; see energy-model.md section 4
DEFAULT_PUE = 1.4  # facility overhead multiplier; documented assumption
HIGH_INTENSITY_THRESHOLD_G_PER_KWH = 400.0
MAX_DEFER_HOURS = {"interactive": 0, "standard": 6, "deferrable": 24}

# 24-hour average grid carbon intensity profiles (gCO2/kWh), hourly, local time.
# Derived from public annual-average shapes (day dip from solar, evening ramp);
# static by design - the gate logic is the demonstration, the feed being static
# is a documented limitation (energy-model.md section 4.3: average vs. MARGINAL
# intensity - savings computed on averages overstate impact; stated, not solved).
_STATIC_CURVES: dict[str, list[float]] = {
    # us-east-1 (Virginia; PJM-like mix): coal/gas base, mild solar dip.
    "us-east-1": [
        380,
        375,
        370,
        368,
        370,
        380,
        400,
        420,
        430,
        420,
        400,
        385,
        370,
        360,
        355,
        360,
        380,
        420,
        450,
        460,
        450,
        430,
        410,
        390,
    ],
    # us-west-2 (Oregon; hydro-heavy): low base, small evening ramp.
    "us-west-2": [
        120,
        118,
        115,
        114,
        115,
        120,
        130,
        140,
        145,
        140,
        130,
        120,
        110,
        105,
        100,
        105,
        115,
        140,
        160,
        165,
        155,
        145,
        135,
        125,
    ],
    # eu-north-1 (Stockholm; hydro/nuclear): very low, nearly flat.
    "eu-north-1": [
        45,
        44,
        43,
        43,
        44,
        46,
        50,
        55,
        58,
        56,
        52,
        48,
        45,
        43,
        42,
        43,
        46,
        52,
        60,
        62,
        58,
        54,
        50,
        47,
    ],
}


class IntensitySource(Protocol):
    """Where gCO2/kWh numbers come from. Static curves ship; live APIs drop in."""

    def intensity_at(self, region: str, hour: int) -> float: ...


class StaticIntensityCurves:
    """The shipped source: static 24-hour regional profiles (see module docstring)."""

    def __init__(self, curves: dict[str, list[float]] | None = None) -> None:
        self._curves = curves if curves is not None else _STATIC_CURVES

    def intensity_at(self, region: str, hour: int) -> float:
        if region not in self._curves:
            raise KeyError(f"unknown region '{region}'; shipped curves: {sorted(self._curves)}")
        return self._curves[region][hour % 24]

    def regions(self) -> list[str]:
        return sorted(self._curves)


class EnergyEstimate(BaseModel):
    """What a job burns, chained on the calibrated runtime term."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    estimated_kwh: float = Field(..., ge=0)
    estimated_gco2: float = Field(..., ge=0)
    intensity_at_decision: float = Field(..., gt=0)
    region: str
    hour_at_decision: int = Field(..., ge=0, le=23)
    utilization_factor: float = Field(..., gt=0, le=1)
    pue: float = Field(..., ge=1)
    tdp_kw: float = Field(..., gt=0)


class ScheduleAdvice(BaseModel):
    """Deferral GUIDANCE attached to a decision - advice, not a queue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    urgency: Urgency
    recommended_start_hour: int = Field(..., ge=0, le=23)
    recommended_intensity: float = Field(..., gt=0)
    run_now_intensity: float = Field(..., gt=0)
    projected_gco2_if_deferred: float = Field(..., ge=0)
    projected_gco2_saved: float  # negative never emitted; 0 when run-now is best
    reason: str


def estimate_energy(
    cost: CostEstimate,
    profile: HardwareProfile,
    intensity_source: IntensitySource,
    region: str,
    hour: int,
    utilization: float | None = None,
    pue: float = DEFAULT_PUE,
) -> EnergyEstimate:
    """kWh and gCO2 for a cost estimate, at a region-hour's grid intensity."""
    tdp = profile.tdp_kw
    util = utilization if utilization is not None else profile.default_utilization
    kwh = tdp * util * cost.total_gpu_hours * pue
    intensity = intensity_source.intensity_at(region, hour)
    return EnergyEstimate(
        estimated_kwh=round(kwh, 6),
        estimated_gco2=round(kwh * intensity, 4),
        intensity_at_decision=intensity,
        region=region,
        hour_at_decision=hour % 24,
        utilization_factor=util,
        pue=pue,
        tdp_kw=tdp,
    )


def trim_carbon_avoided(original: EnergyEstimate, modified: EnergyEstimate) -> tuple[float, float]:
    """(kwh_avoided, gco2_avoided) from a value-trim: the carbon of the frames
    the gate removed because they added no expected training value. The v2
    headline number - waste elimination, before any scheduling cleverness."""
    kwh = max(0.0, original.estimated_kwh - modified.estimated_kwh)
    gco2 = max(0.0, original.estimated_gco2 - modified.estimated_gco2)
    return round(kwh, 6), round(gco2, 4)


def schedule_advice(
    energy: EnergyEstimate,
    urgency: Urgency,
    intensity_source: IntensitySource,
    high_threshold: float = HIGH_INTENSITY_THRESHOLD_G_PER_KWH,
) -> ScheduleAdvice:
    """Deterministic window guidance per urgency class (config-driven).

    interactive: never advised to wait (carbon logged only).
    standard: advised to a sub-threshold hour only if run-now intensity exceeds
      `high_threshold` and such an hour exists within its defer budget.
    deferrable: advised to the minimum-intensity hour within its defer budget.
    """
    now = energy.hour_at_decision
    run_now = energy.intensity_at_decision
    horizon = MAX_DEFER_HOURS[urgency]

    best_hour, best_intensity = now, run_now
    if horizon > 0:
        for delta in range(1, horizon + 1):
            h = (now + delta) % 24
            i = intensity_source.intensity_at(energy.region, h)
            if i < best_intensity:
                best_hour, best_intensity = h, i

    defer = False
    if urgency == "deferrable":
        defer = best_hour != now
        reason = (
            f"lowest-intensity window within {horizon}h"
            if defer
            else "current hour is already the lowest-intensity window"
        )
    elif urgency == "standard":
        defer = run_now > high_threshold and best_intensity <= high_threshold
        reason = (
            f"intensity {run_now:.0f} exceeds threshold {high_threshold:.0f}; "
            f"sub-threshold window found within {horizon}h"
            if defer
            else "run now (below threshold, or no sub-threshold window in budget)"
        )
    else:
        reason = "interactive: never deferred; carbon logged only"

    target_hour = best_hour if defer else now
    target_intensity = best_intensity if defer else run_now
    kwh = energy.estimated_kwh
    projected = round(kwh * target_intensity, 4)
    saved = round(max(0.0, kwh * run_now - projected), 4)
    return ScheduleAdvice(
        urgency=urgency,
        recommended_start_hour=target_hour,
        recommended_intensity=target_intensity,
        run_now_intensity=run_now,
        projected_gco2_if_deferred=projected,
        projected_gco2_saved=saved,
        reason=reason,
    )
