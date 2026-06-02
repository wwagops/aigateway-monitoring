"""Chargement du YAML → cibles résolues (deep-merge des capacités + secrets via env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..logging import get_logger
from .schema import CapabilitySpec, RootConfig

log = get_logger(__name__)


@dataclass
class ResolvedTarget:
    """Une cible concrète à sonder : un modèle d'une organisation."""

    organization: str
    base_url: str
    model: str
    api_key: str | None
    max_tokens: int
    capabilities: dict[str, CapabilitySpec] = field(default_factory=dict)

    @property
    def enabled_capabilities(self) -> list[str]:
        return sorted(name for name, spec in self.capabilities.items() if spec.enabled)


@dataclass
class OrgSummary:
    name: str
    base_url: str
    models: list[str]


@dataclass
class LoadedConfig:
    targets: list[ResolvedTarget]
    organizations: list[OrgSummary]


def _merge_caps(*levels: dict[str, CapabilitySpec]) -> dict[str, CapabilitySpec]:
    """Fusionne les capacités, les niveaux suivants écrasant les précédents (par clé)."""
    merged: dict[str, CapabilitySpec] = {}
    for level in levels:
        for name, spec in level.items():
            merged[name] = spec
    return merged


def _first_not_none(*values: int | None) -> int:
    """Première valeur non nulle (le dernier niveau, défauts globaux, est toujours défini)."""
    for value in values:
        if value is not None:
            return value
    raise ValueError("aucune valeur définie")  # ne devrait jamais arriver (defaults.max_tokens)


def _resolve_api_key(env_name: str | None, org_name: str) -> str | None:
    if not env_name:
        return None
    value = os.environ.get(env_name)
    if not value:
        log.warning(
            "api_key_env défini mais variable absente",
            organization=org_name,
            api_key_env=env_name,
        )
    return value


def load_config(path: str | Path) -> LoadedConfig:
    """Lit et valide le fichier YAML, renvoie les cibles résolues + résumés d'orgs."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Fichier de configuration introuvable : {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    root = RootConfig.model_validate(raw)

    targets: list[ResolvedTarget] = []
    summaries: list[OrgSummary] = []

    for org in root.organizations:
        api_key = _resolve_api_key(org.api_key_env, org.name)

        for model in org.models:
            # Registre par nom de modèle (s'applique à ce modèle dans toutes les orgs).
            registry = root.model_defaults.get(model.name)
            registry_caps = registry.capabilities if registry is not None else {}
            registry_max_tokens = registry.max_tokens if registry is not None else None

            # Précédence (du moins au plus spécifique) :
            # défauts globaux < org < registre par nom de modèle < (org, modèle).
            caps = _merge_caps(
                root.defaults.capabilities,
                org.capabilities,
                registry_caps,
                model.capabilities,
            )
            max_tokens = _first_not_none(
                model.max_tokens,
                registry_max_tokens,
                org.max_tokens,
                root.defaults.max_tokens,
            )
            targets.append(
                ResolvedTarget(
                    organization=org.name,
                    base_url=org.base_url,
                    model=model.name,
                    api_key=api_key,
                    max_tokens=max_tokens,
                    capabilities=caps,
                )
            )

        summaries.append(
            OrgSummary(name=org.name, base_url=org.base_url, models=[m.name for m in org.models])
        )

    return LoadedConfig(targets=targets, organizations=summaries)
