"""Chargement et validation de la configuration des cibles (YAML)."""

from .loader import LoadedConfig, OrgSummary, ResolvedTarget, load_config
from .schema import Capabilities, CapabilitySpec, RootConfig

__all__ = [
    "Capabilities",
    "CapabilitySpec",
    "LoadedConfig",
    "OrgSummary",
    "ResolvedTarget",
    "RootConfig",
    "load_config",
]
