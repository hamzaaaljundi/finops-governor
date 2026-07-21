"""One-off: re-derive cost-model.md section-6 numbers from current constants (9.3 sweep)."""

import json
from pathlib import Path

from finops_governor.estimator import GpuRenderCostModel, get_profile
from finops_governor.schemas import GenerationPlan

FIXTURES = Path("fixtures")


def load(p: str) -> GenerationPlan:
    return GenerationPlan.model_validate(json.loads(Path(p).read_text()))


plans = {
    "6.1 minimal": load("fixtures/plans/valid/minimal.json"),
    "6.2/6.3 multi_scene": load("fixtures/plans/valid/multi_scene.json"),
    "production_scale (CLI test)": load("fixtures/diversity/redundant/production_scale.json"),
}

for name, plan in plans.items():
    print(f"\n=== {name} (modalities: {[m.value for m in plan.modalities]}) ===")
    for pid in ("t4", "a10g", "h100"):
        est = GpuRenderCostModel(get_profile(pid)).estimate(plan)
        print(
            f"  {pid:5s}  images={est.total_images:>7}  gpu_hours={est.total_gpu_hours:.4f}  usd=${est.total_usd:.4f}"
        )
