"""v2.0-energy demo: the three-act carbon story, printed from real gate decisions.

Run from the repo root:  python demo/energy_demo.py
"""

import json
from pathlib import Path

from finops_governor.estimator import GpuRenderCostModel, load_profiles
from finops_governor.governor import Governor
from finops_governor.schemas import GenerationPlan

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def main() -> None:
    profile = load_profiles()["a10g"]
    gov = Governor.with_default_checks(GpuRenderCostModel(profile))
    # Fixed decision hour (19:00 = evening grid peak) so the demo is reproducible:
    gov._energy_hour = 19  # demo-only override; production uses the current hour

    print("=" * 72)
    print("ACT 1 - the headline: value-trim IS carbon reduction")
    print("=" * 72)
    red = GenerationPlan.model_validate(
        json.loads((FIXTURES / "diversity" / "redundant" / "production_scale.json").read_text())
    )
    d = gov.evaluate(red)
    assert d.energy and d.modified_energy and d.schedule
    print(f"verdict: {d.verdict.value}")
    print(
        f"as-declared:   {d.energy.estimated_kwh:9.3f} kWh  {d.energy.estimated_gco2 / 1000:8.2f} kg CO2"
    )
    print(
        f"value-trimmed: {d.modified_energy.estimated_kwh:9.3f} kWh  {d.modified_energy.estimated_gco2 / 1000:8.2f} kg CO2"
    )
    print(
        f"AVOIDED by not rendering redundant frames: {d.kwh_avoided_by_trim:.3f} kWh, "
        f"{(d.gco2_avoided_by_trim or 0) / 1000:.2f} kg CO2"
    )

    print()
    print("=" * 72)
    print("ACT 2 - deferral advice (guidance, not a queue)")
    print("=" * 72)
    data = json.loads((FIXTURES / "plans" / "valid" / "minimal.json").read_text())
    data["urgency"] = "deferrable"
    d2 = gov.evaluate(GenerationPlan.model_validate(data))
    assert d2.schedule and d2.energy
    s = d2.schedule
    print(
        f"urgency: {s.urgency} | now: hour {d2.energy.hour_at_decision} @ {s.run_now_intensity:.0f} gCO2/kWh"
    )
    print(
        f"advice:  start hour {s.recommended_start_hour} @ {s.recommended_intensity:.0f} gCO2/kWh"
    )
    print(f"projected saving if deferred: {s.projected_gco2_saved:.3f} g CO2  ({s.reason})")

    print()
    print("=" * 72)
    print("ACT 3 - the governance rule: urgency promotion needs a human")
    print("=" * 72)
    data.update(urgency="interactive", urgency_reclassified_from="deferrable")
    d3 = gov.evaluate(GenerationPlan.model_validate(data))
    print(f"unapproved reclass -> {d3.verdict.value}: {d3.reason}")
    data["approved_reclass"] = True
    d4 = gov.evaluate(GenerationPlan.model_validate(data))
    print(f"approved reclass   -> {d4.verdict.value} (audit-visible in the saved plan)")


if __name__ == "__main__":
    main()
