"""USD geometric validity check (M5, Task 5.4).

The geometry axis of the Governor. Loads each scene's composed USD stage (M5 convention:
the stage path is Scene.environment.usd_path - see docs/geometry-model.md section 2) and
runs four pre-render checks over world-space bounding boxes:

  1. Asset existence            - stage opens; every asset_id resolves   -> BLOCKING
  2. Asset-vs-environment clip  - penetration beyond tolerance           -> BLOCKING
  3. Asset-vs-asset overlap     - penetration beyond tolerance           -> WARNING
  4. Camera framing             - camera oriented away from the scene    -> WARNING

Collision uses penetration depth (shallowest-axis AABB overlap) with a resting tolerance,
so objects sitting on the floor do not fire. Framing is a deliberately coarse dot-product
orientation proxy (no frustum, no occlusion). Assumptions and limits are documented in
docs/geometry-model.md section 6.

Pure read: the check mutates nothing; stages are loaded lazily and memoized per loader.
"""

import math

from finops_governor.schemas import Camera, Scene
from finops_governor.validity.models import CheckContext, Finding, Severity
from finops_governor.validity.usd_stage import UsdStageError, UsdStageLoader

_DEFAULT_PENETRATION_EPSILON_M = 0.01

_Range = tuple[tuple[float, float, float], tuple[float, float, float]]


def _penetration_depth(a: _Range, b: _Range) -> float:
    """Shallowest-axis overlap of two AABBs; 0.0 when they do not intersect."""
    (amin, amax), (bmin, bmax) = a, b
    overlaps = [min(amax[i], bmax[i]) - max(amin[i], bmin[i]) for i in range(3)]
    if any(o <= 0 for o in overlaps):
        return 0.0
    return min(overlaps)


def _camera_forward(camera: Camera) -> tuple[float, float, float]:
    """Camera forward direction: local -Z rotated by the camera's Euler rotation.

    Matches the USD camera convention and the schema's Euler-degrees rotation, applied
    in X, Y, Z order (verified against Gf.Rotation composition in the design spec).
    """
    rx, ry, rz = (math.radians(d) for d in camera.transform.rotation)
    # Start from local -Z and apply Rx, then Ry, then Rz.
    x, y, z = 0.0, 0.0, -1.0
    # Rx
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    # Ry
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    # Rz
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return (x, y, z)


class UsdGeometryCheck:
    name = "usd_geometry"

    def __init__(
        self,
        loader: UsdStageLoader | None = None,
        penetration_epsilon_m: float = _DEFAULT_PENETRATION_EPSILON_M,
    ) -> None:
        self._loader = loader if loader is not None else UsdStageLoader()
        self._epsilon = penetration_epsilon_m

    def check(self, context: CheckContext) -> list[Finding]:
        findings: list[Finding] = []
        for scene in context.plan.scenes:
            findings.extend(self._check_scene(scene))
        return findings

    # ------------------------------------------------------------------ #
    # Per-scene logic
    # ------------------------------------------------------------------ #

    def _check_scene(self, scene: Scene) -> list[Finding]:
        stage_path = scene.environment.usd_path

        # Check 1a: the scene's stage must open at all.
        try:
            stage = self._loader.load(stage_path)
        except UsdStageError:
            return [
                Finding(
                    check_name=self.name,
                    severity=Severity.BLOCKING,
                    reason=(
                        f"scene '{scene.scene_id}': stage '{stage_path}' does not "
                        "resolve or cannot be opened."
                    ),
                    detail={"scene_id": scene.scene_id, "stage_path": stage_path},
                )
            ]

        bounds = self._world_bounds(stage)
        findings: list[Finding] = []

        # Check 1b: environment and every declared asset must resolve to a prim.
        required = [scene.environment.asset_id] + [a.asset_id for a in scene.assets]
        missing = [asset_id for asset_id in required if asset_id not in bounds]
        for asset_id in missing:
            findings.append(
                Finding(
                    check_name=self.name,
                    severity=Severity.BLOCKING,
                    reason=(
                        f"scene '{scene.scene_id}': asset '{asset_id}' does not "
                        f"resolve to a prim in stage '{stage_path}'."
                    ),
                    detail={"scene_id": scene.scene_id, "asset_id": asset_id},
                )
            )

        env_id = scene.environment.asset_id
        present_assets = [a.asset_id for a in scene.assets if a.asset_id not in missing]

        # Check 2: asset-vs-environment penetration (BLOCKING).
        if env_id not in missing:
            for asset_id in present_assets:
                depth = _penetration_depth(bounds[asset_id], bounds[env_id])
                if depth > self._epsilon:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.BLOCKING,
                            reason=(
                                f"scene '{scene.scene_id}': asset '{asset_id}' "
                                f"penetrates environment '{env_id}' by "
                                f"{depth:.3f} m (tolerance {self._epsilon} m)."
                            ),
                            detail={
                                "scene_id": scene.scene_id,
                                "asset_id": asset_id,
                                "environment_id": env_id,
                                "penetration_m": round(depth, 4),
                            },
                        )
                    )

        # Check 3: asset-vs-asset penetration (WARNING).
        for i, a in enumerate(present_assets):
            for b in present_assets[i + 1 :]:
                depth = _penetration_depth(bounds[a], bounds[b])
                if depth > self._epsilon:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.WARNING,
                            reason=(
                                f"scene '{scene.scene_id}': assets '{a}' and '{b}' "
                                f"interpenetrate by {depth:.3f} m "
                                f"(tolerance {self._epsilon} m)."
                            ),
                            detail={
                                "scene_id": scene.scene_id,
                                "asset_a": a,
                                "asset_b": b,
                                "penetration_m": round(depth, 4),
                            },
                        )
                    )

        # Check 4: camera framing (WARNING) - orientation proxy over asset centroid.
        if present_assets:
            centers = [
                tuple((lo[i] + hi[i]) / 2 for i in range(3))
                for lo, hi in (bounds[a] for a in present_assets)
            ]
            n = len(centers)
            scene_center = tuple(sum(c[i] for c in centers) / n for i in range(3))
            for camera in scene.cameras:
                dot = self._framing_dot(camera, scene_center)
                if dot <= 0:
                    findings.append(
                        Finding(
                            check_name=self.name,
                            severity=Severity.WARNING,
                            reason=(
                                f"scene '{scene.scene_id}': camera "
                                f"'{camera.camera_id}' is oriented away from the "
                                f"scene (dot={dot:.2f}); it would render empty "
                                "frames."
                            ),
                            detail={
                                "scene_id": scene.scene_id,
                                "camera_id": camera.camera_id,
                                "dot": round(dot, 4),
                            },
                        )
                    )

        return findings

    # ------------------------------------------------------------------ #
    # Geometry helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _world_bounds(stage) -> dict[str, _Range]:
        """World-space AABB per geometry prim, keyed by prim name (= asset_id)."""
        from pxr import Usd, UsdGeom

        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
        bounds: dict[str, _Range] = {}
        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Boundable):
                r = cache.ComputeWorldBound(prim).ComputeAlignedRange()
                if r.IsEmpty():
                    continue
                lo, hi = r.GetMin(), r.GetMax()
                bounds[prim.GetName()] = (
                    (lo[0], lo[1], lo[2]),
                    (hi[0], hi[1], hi[2]),
                )
        return bounds

    @staticmethod
    def _framing_dot(camera: Camera, scene_center: tuple[float, float, float]) -> float:
        fwd = _camera_forward(camera)
        pos = camera.transform.translation
        to_scene = tuple(scene_center[i] - pos[i] for i in range(3))
        norm = math.sqrt(sum(c * c for c in to_scene))
        if norm == 0:
            return 1.0  # camera at the centroid: cannot be "aimed away"
        to_scene = tuple(c / norm for c in to_scene)
        return sum(fwd[i] * to_scene[i] for i in range(3))
