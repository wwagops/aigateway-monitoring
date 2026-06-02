"""Tests de chargement de la config : deep-merge des capacités, sondes, précédence env."""

from __future__ import annotations

from pathlib import Path

from aigw_monitor.checks.capabilities import selected_probes
from aigw_monitor.config.loader import load_config
from aigw_monitor.settings import Settings

CONFIG = """
monitor:
  database_url: postgresql+asyncpg://u:p@db/x
  schedule: 120
  max_concurrency: 4

defaults:
  max_tokens: 8
  capabilities:
    tool_calling: false
    reasoning: false

organizations:
  - name: acme
    base_url: https://gw.acme/v1
    api_key_env: ACME_KEY
    capabilities:
      tool_calling: true
    models:
      - name: qwen
      - name: deepseek-r1
        capabilities:
          reasoning:
            enabled: true
            extra_body: { chat_template_kwargs: { enable_thinking: true } }
  - name: research
    base_url: https://gw.research/v1
    models:
      - name: gpt-oss
"""


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def test_capabilities_deep_merge_and_probes(tmp_path, monkeypatch):
    monkeypatch.setenv("ACME_KEY", "sk-secret")
    cfg = load_config(_write(tmp_path))

    targets = {(t.organization, t.model): t for t in cfg.targets}
    assert set(targets) == {
        ("acme", "qwen"),
        ("acme", "deepseek-r1"),
        ("research", "gpt-oss"),
    }

    # qwen hérite tool_calling=true de l'org, pas de reasoning.
    qwen = targets[("acme", "qwen")]
    assert qwen.enabled_capabilities == ["tool_calling"]
    assert selected_probes(qwen) == ["liveness", "tool_calling"]
    assert qwen.api_key == "sk-secret"

    # deepseek hérite tool_calling et ajoute reasoning.
    ds = targets[("acme", "deepseek-r1")]
    assert ds.enabled_capabilities == ["reasoning", "tool_calling"]
    assert selected_probes(ds) == ["liveness", "tool_calling", "reasoning"]
    assert ds.capabilities["reasoning"].extra_body == {
        "chat_template_kwargs": {"enable_thinking": True}
    }

    # research/gpt-oss : aucune capacité -> liveness seulement, pas de clé.
    gpt = targets[("research", "gpt-oss")]
    assert gpt.enabled_capabilities == []
    assert selected_probes(gpt) == ["liveness"]
    assert gpt.api_key is None
    assert gpt.max_tokens == 8  # hérité de defaults


def test_settings_env_overrides_yaml(tmp_path, monkeypatch):
    path = _write(tmp_path)
    monkeypatch.setenv("AIGW_CONFIG_PATH", str(path))

    # Sans surcharge : valeur issue du bloc monitor: du YAML.
    monkeypatch.delenv("AIGW_SCHEDULE", raising=False)
    assert Settings().schedule == 120

    # Avec surcharge env : l'env l'emporte.
    monkeypatch.setenv("AIGW_SCHEDULE", "999")
    assert Settings().schedule == 999


def test_settings_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AIGW_CONFIG_PATH", str(tmp_path / "absent.yaml"))
    monkeypatch.delenv("AIGW_SCHEDULE", raising=False)
    # Aucun fichier -> valeur par défaut du champ.
    assert Settings().schedule == 60


def test_database_url_defaults_to_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("AIGW_CONFIG_PATH", str(tmp_path / "absent.yaml"))
    monkeypatch.delenv("AIGW_DATABASE_URL", raising=False)
    # Aucune URL fournie -> SQLite local.
    s = Settings()
    assert s.database_url.startswith("sqlite")
    assert s.is_sqlite is True

    # Une URL explicite (env) l'emporte et n'est pas considérée SQLite.
    monkeypatch.setenv("AIGW_DATABASE_URL", "postgresql+asyncpg://u:p@h/d")
    s2 = Settings()
    assert s2.database_url == "postgresql+asyncpg://u:p@h/d"
    assert s2.is_sqlite is False


CONFIG_REGISTRY = """
defaults:
  max_tokens: 8
  capabilities:
    tool_calling: false
    reasoning: false

# Capacités par nom de modèle, partagées entre organisations.
model_defaults:
  gpt-oss-120b:
    max_tokens: 64
    capabilities:
      tool_calling: true
      reasoning: true

organizations:
  - name: a
    base_url: https://a/v1
    models:
      - name: gpt-oss-120b            # hérite tout du registre
  - name: b
    base_url: https://b/v1
    capabilities:
      tool_calling: false             # org désactive le tool calling...
    models:
      - name: gpt-oss-120b
        capabilities:
          reasoning: false            # ...et (org,modèle) désactive le reasoning
      - name: other                   # hors registre, aucune capa
"""


def test_model_defaults_applies_across_orgs_and_precedence(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_REGISTRY, encoding="utf-8")
    cfg = load_config(path)
    targets = {(t.organization, t.model): t for t in cfg.targets}

    # Org "a" : le registre s'applique intégralement (tool + reasoning + max_tokens).
    a = targets[("a", "gpt-oss-120b")]
    assert a.enabled_capabilities == ["reasoning", "tool_calling"]
    assert selected_probes(a) == ["liveness", "tool_calling", "reasoning"]
    assert a.max_tokens == 64  # vient de model_defaults, pas des defaults globaux (8)

    # Org "b" : le registre (tool=true) BAT le défaut d'org (tool=false) ;
    # mais l'override (org, modèle) (reasoning=false) BAT le registre.
    b = targets[("b", "gpt-oss-120b")]
    assert b.enabled_capabilities == ["tool_calling"]
    assert selected_probes(b) == ["liveness", "tool_calling"]
    assert b.max_tokens == 64

    # Modèle hors registre, aucune capacité -> liveness seulement.
    other = targets[("b", "other")]
    assert other.enabled_capabilities == []
    assert selected_probes(other) == ["liveness"]
    assert other.max_tokens == 8
