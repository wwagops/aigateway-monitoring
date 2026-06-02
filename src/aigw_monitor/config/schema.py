"""Schémas Pydantic décrivant le fichier YAML de configuration des cibles."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Méthode de sonde liveness : appel réel de complétion (défaut) ou GET /v1/models (léger).
LivenessMethod = Literal["chat", "models"]


class CapabilitySpec(BaseModel):
    """Déclaration d'une capacité d'un modèle.

    Forme courte ``true``/``false`` acceptée (→ ``enabled``), ou forme objet
    ``{enabled: true, extra_body: {...}}`` pour passer des paramètres déclencheurs
    spécifiques au provider (ex. activer le *thinking*).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return {"enabled": value}
        return value


class Capabilities(BaseModel):
    """Ensemble nommé de capacités (clé = nom de capacité)."""

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _wrap(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: CapabilitySpec.model_validate(v) for k, v in value.items()}
        return value

    def as_dict(self) -> dict[str, CapabilitySpec]:
        out: dict[str, CapabilitySpec] = {}
        for name, spec in self.__dict__.items():
            if isinstance(spec, CapabilitySpec):
                out[name] = spec
        return out


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    max_tokens: int | None = None
    liveness: LivenessMethod | None = None
    capabilities: dict[str, CapabilitySpec] = Field(default_factory=dict)


class OrgEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    base_url: str
    api_key_env: str | None = None
    max_tokens: int | None = None
    liveness: LivenessMethod | None = None
    capabilities: dict[str, CapabilitySpec] = Field(default_factory=dict)
    models: list[ModelEntry]


class DefaultsEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tokens: int = 16
    liveness: LivenessMethod = "chat"
    capabilities: dict[str, CapabilitySpec] = Field(default_factory=dict)


class ModelDefaultsEntry(BaseModel):
    """Capacités/paramètres par **nom de modèle**, appliqués dans toutes les organisations."""

    model_config = ConfigDict(extra="forbid")

    max_tokens: int | None = None
    liveness: LivenessMethod | None = None
    capabilities: dict[str, CapabilitySpec] = Field(default_factory=dict)


class RootConfig(BaseModel):
    """Racine du fichier YAML."""

    model_config = ConfigDict(extra="forbid")

    # Le bloc monitor: est consommé par Settings ; on l'accepte ici sans le re-valider.
    monitor: dict[str, Any] = Field(default_factory=dict)
    defaults: DefaultsEntry = Field(default_factory=DefaultsEntry)
    # Registre par nom de modèle, partagé entre organisations (clé = nom du modèle).
    model_defaults: dict[str, ModelDefaultsEntry] = Field(default_factory=dict)
    organizations: list[OrgEntry] = Field(default_factory=list)
