"""Test end-to-end : run_cycle (respx) -> persistance sqlite -> API REST (ASGITransport)."""

from __future__ import annotations

import httpx
import pytest
import respx

from aigw_monitor.api import create_app
from aigw_monitor.checks.runner import run_cycle
from aigw_monitor.config.loader import LoadedConfig, OrgSummary, ResolvedTarget
from aigw_monitor.config.schema import CapabilitySpec
from aigw_monitor.metrics import PrometheusMetrics
from aigw_monitor.settings import Settings

ACME = "https://gw.acme/v1"


def _loaded_config() -> LoadedConfig:
    qwen = ResolvedTarget(
        organization="acme",
        base_url=ACME,
        model="qwen",
        api_key=None,
        max_tokens=16,
        capabilities={"tool_calling": CapabilitySpec(enabled=True)},
    )
    gpt = ResolvedTarget(
        organization="acme",
        base_url=ACME,
        model="gpt-oss",
        api_key=None,
        max_tokens=16,
        capabilities={},
    )
    orgs = [OrgSummary(name="acme", base_url=ACME, models=["qwen", "gpt-oss"])]
    return LoadedConfig(targets=[qwen, gpt], organizations=orgs)


@pytest.fixture
def settings(monkeypatch, tmp_path) -> Settings:
    monkeypatch.setenv("AIGW_CONFIG_PATH", str(tmp_path / "none.yaml"))
    monkeypatch.delenv("AIGW_EXPOSE_BASE_URL", raising=False)
    return Settings()


@respx.mock
async def test_end_to_end(session_factory, settings):
    respx.post(f"{ACME}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "ok", "tool_calls": [{"id": "1", "function": {}}]}}
                ]
            },
        )
    )

    config = _loaded_config()
    summary = await run_cycle(
        targets=config.targets,
        settings=settings,
        session_factory=session_factory,
        trigger="manual",
    )
    assert summary.total == 2
    assert summary.up == 2
    assert summary.run_id is not None

    app = create_app(settings, session_factory, config, metrics=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = (await client.get("/health")).json()
        assert health["status"] == "ok"
        assert health["database"] == "ok"
        assert health["targets"] == 2

        models = (await client.get("/api/models")).json()
        by_model = {m["model"]: m for m in models}
        assert by_model["qwen"]["probes"] == ["liveness", "tool_calling"]
        assert by_model["gpt-oss"]["probes"] == ["liveness"]
        # base_url masquée par défaut
        assert by_model["qwen"]["base_url"] is None

        status = (await client.get("/api/status")).json()
        status_by_model = {s["model"]: s for s in status}
        assert status_by_model["qwen"]["liveness_status"] == "UP"
        # La sonde up/down est nommée comme une capacité (méthode chat par défaut).
        assert status_by_model["qwen"]["liveness_probe"] == "chat_completion"
        qwen_tool = status_by_model["qwen"]["capabilities"]["tool_calling"]
        assert qwen_tool["status"] == "AVAILABLE"
        assert qwen_tool["latency_ms"] is not None  # latence par test exposée
        # gpt-oss : capacité non déclarée -> sonde non exécutée
        assert status_by_model["gpt-oss"]["capabilities"]["tool_calling"]["status"] == "SKIPPED"

        runs = (await client.get("/api/runs")).json()
        assert len(runs) == 1
        run_detail = (await client.get(f"/api/runs/{runs[0]['id']}")).json()
        assert len(run_detail["checks"]) == 2

        history = (await client.get("/api/models/acme/qwen/history")).json()
        assert len(history) >= 1


@respx.mock
async def test_metrics_endpoint_returns_200_without_redirect(session_factory, settings):
    respx.post(f"{ACME}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "ok", "tool_calls": [{"id": "1", "function": {}}]}}
                ]
            },
        )
    )
    config = _loaded_config()
    metrics = PrometheusMetrics()
    await run_cycle(targets=config.targets, settings=settings, metrics=metrics, trigger="manual")

    app = create_app(settings, session_factory, config, metrics=metrics)
    transport = httpx.ASGITransport(app=app)
    # follow_redirects=False par défaut : un 307 ferait échouer l'assert.
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 200
    # La gauge up/down porte un label probe nommant la sonde (comme capability).
    assert 'aigw_model_up{model="qwen",org="acme",probe="chat_completion"} 1.0' in resp.text
    assert (
        'aigw_model_capability_available{capability="tool_calling",model="qwen",org="acme"} 1.0'
        in resp.text
    )


@respx.mock
async def test_expose_base_url_flag(session_factory, monkeypatch, tmp_path):
    monkeypatch.setenv("AIGW_CONFIG_PATH", str(tmp_path / "none.yaml"))
    monkeypatch.setenv("AIGW_EXPOSE_BASE_URL", "true")
    settings = Settings()
    assert settings.expose_base_url is True

    config = _loaded_config()
    app = create_app(settings, session_factory, config, metrics=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        models = (await client.get("/api/models")).json()
        assert all(m["base_url"] == ACME for m in models)
