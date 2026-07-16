"""Signal package."""
from twa.signal.engine import (
    DEFAULT_CFG, EngineConfig, build_factor_vector, compute_signal,
    normalise_factor, project_symbol_factors, atr,
)
__all__ = [
    "DEFAULT_CFG", "EngineConfig", "build_factor_vector", "compute_signal",
    "normalise_factor", "project_symbol_factors", "atr",
]
