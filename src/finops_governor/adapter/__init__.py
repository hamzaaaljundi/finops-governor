"""Adapter: GenerationPlan -> runnable execution-stack scripts (v1: Replicator)."""

from finops_governor.adapter.replicator import AdapterError, generate_replicator_script

__all__ = [
    "AdapterError",
    "generate_replicator_script",
]
