"""Lazy USD stage loading (M5, Task 5.1).

A memoizing loader that opens USD stages on demand. Per ADR 0006, lazy stage access lives
here - owned by the geometry check that needs it - not on the shared CheckContext: only the
geometry axis consumes stages, and keeping them out of the context preserves the context's
serializability and keeps the heavy pxr dependency isolated to this one place.

Laziness: a stage is opened only when first requested, so a check that never inspects
geometry pays nothing. Memoization: each path is opened at most once per loader, so a plan's
stages are not re-read across scenes or checks.
"""

from pxr import Tf, Usd


class UsdStageError(Exception):
    """Raised when a USD stage cannot be opened (missing or unreadable)."""


class UsdStageLoader:
    def __init__(self) -> None:
        self._cache: dict[str, Usd.Stage] = {}

    def load(self, path: str) -> Usd.Stage:
        """Open (and cache) the stage at `path`. Raises UsdStageError if it cannot open."""
        if path not in self._cache:
            try:
                stage = Usd.Stage.Open(path)
            except Tf.ErrorException as exc:
                raise UsdStageError(f"could not open USD stage: {path}") from exc
            if not stage:
                raise UsdStageError(f"could not open USD stage: {path}")
            self._cache[path] = stage
        return self._cache[path]
