"""s4_raster_timed - session-4 D3: rasterize_factor with sub-second timing.

Render logic identical to the frozen session-3 r5_raster.py (rtx_realtime, same scene,
same camera, same randomization) EXCEPT: 300 frames (r5's own stability-clause
extension) and an in-app frame watcher writing time.monotonic() per frame to a sidecar
JSON - the sub-second timing source ADR 0009's amendment named as the requirement for
any future rasterize_factor measurement (filesystem mtimes quantize at 1s against a
~0.07s/frame signal; the watcher polls at 5ms, ~14x finer than the signal).

The watcher is pure stdlib (thread + glob + monotonic) - no Replicator API dependency,
so it cannot break on an Isaac Sim version change. Instrumentation only; render logic
untouched.
"""

from isaacsim import SimulationApp

simulation_app = SimulationApp({"headless": True})

# --- s4 instrumentation: sub-second frame timing (ADR 0009 amendment) --------------
import json as _json
import threading as _threading
import time as _time
from pathlib import Path as _Path

_OUT_DIR = "/kit/out/s4_raster"
_SIDECAR = "/kit/out/s4_raster_times.json"


def _watch() -> None:
    seen: dict[str, float] = {}
    out = _Path(_OUT_DIR)
    while True:
        now = _time.monotonic()
        new = False
        if out.exists():
            for f in out.rglob("rgb_*.png"):
                if f.name not in seen:
                    seen[f.name] = now
                    new = True
        if new:
            _Path(_SIDECAR).write_text(_json.dumps(seen))
        _time.sleep(0.005)


_threading.Thread(target=_watch, daemon=True).start()
# --- end instrumentation -----------------------------------------------------------

import omni.replicator.core as rep

rep.settings.set_render_rtx_realtime()

with rep.new_layer():
    environment = rep.create.from_usd('/kit/assets/floor.usda')
    asset_0 = rep.create.from_usd('/kit/assets/arm.usda')  # arm
    asset_1 = rep.create.from_usd('/kit/assets/box.usda')  # box
    assets = rep.create.group([asset_0, asset_1])

    camera_0 = rep.create.camera(position=(0.0, 2.0, 6.0), rotation=(-15.0, 0.0, 0.0))  # cam
    render_products = [rep.create.render_product(camera_0, (1920, 1080))]

    scene_light = rep.create.light(light_type='Sphere', position=(0, 4, 0), intensity=1500.0)

    with rep.trigger.on_frame(num_frames=300):
        rep.modify.pose(input_prims=assets, rotation=rep.distribution.choice([(0, y, 0) for y in [0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0, 210.0, 240.0, 270.0, 300.0, 330.0]]))  # azimuth
        rep.modify.attribute('intensity', rep.distribution.choice([500.0, 1000.0, 1500.0, 2000.0, 2500.0]), input_prims=scene_light)  # lighting

    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(output_dir='/kit/out/s4_raster', rgb=True)
    writer.attach(render_products)

rep.orchestrator.run_until_complete()

# Give the watcher one final pass to catch the last frames before the app closes.
_time.sleep(0.5)
simulation_app.close()
