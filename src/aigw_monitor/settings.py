"""Paramètres runtime de l'application.

Les valeurs sont empilées par ordre de précédence (du plus prioritaire au moins
prioritaire) : arguments d'init < variables d'environnement ``AIGW_*`` < bloc ``monitor:``
du fichier YAML de configuration < valeurs par défaut des champs.

→ tout paramètre peut être réglé via le fichier de conf OU surchargé par une variable d'env.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

DEFAULT_CONFIG_PATH = "config.yaml"


def _config_path_from_env() -> Path:
    return Path(os.environ.get("AIGW_CONFIG_PATH", DEFAULT_CONFIG_PATH))


class YamlMonitorSource(PydanticBaseSettingsSource):
    """Source pydantic-settings qui lit le bloc ``monitor:`` du fichier YAML."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        self._data: dict[str, Any] = {}
        path = _config_path_from_env()
        if path.is_file():
            with path.open("r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            monitor = loaded.get("monitor") if isinstance(loaded, dict) else None
            if isinstance(monitor, dict):
                self._data = monitor

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field_name, field in self.settings_cls.model_fields.items():
            value, key, _ = self.get_field_value(field, field_name)
            if value is not None:
                values[key] = value
        return values


class Settings(BaseSettings):
    """Configuration runtime de l'application."""

    model_config = SettingsConfigDict(
        env_prefix="AIGW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Chemin du fichier YAML (cibles + bloc monitor). Surcharge : AIGW_CONFIG_PATH.
    config_path: Path = Path(DEFAULT_CONFIG_PATH)

    # Base de données (driver async). Surcharge : AIGW_DATABASE_URL.
    # Défaut : SQLite local (schéma créé automatiquement). Pour la prod, fournir une URL
    # PostgreSQL (ex. postgresql+asyncpg://user:pass@host/db) et appliquer `alembic upgrade head`.
    database_url: str = "sqlite+aiosqlite:///aigw.db"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    # Planification : intervalle en secondes (int) OU expression cron (str). AIGW_SCHEDULE.
    schedule: int | str = 60

    # Appels sortants vers les gateways.
    http_timeout_seconds: float = 30.0
    max_concurrency: int = 16

    # Serveur HTTP (API REST + /metrics).
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    metrics_path: str = "/metrics"

    # Sécurité : masquer les base_url internes dans l'API par défaut.
    expose_base_url: bool = False

    log_level: str = "INFO"

    @field_validator("schedule", mode="before")
    @classmethod
    def _normalize_schedule(cls, value: object) -> object:
        # Les env vars sont des chaînes : "60" -> 60 (intervalle) ; "*/5 * * * *" reste cron.
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Le premier élément a la priorité la plus haute.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlMonitorSource(settings_cls),
            file_secret_settings,
        )
