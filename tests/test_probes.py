"""Tests des sondes (mapping des statuts) via respx."""

from __future__ import annotations

import httpx
import respx

from aigw_monitor.checks.client import OpenAICompatClient
from aigw_monitor.checks.probes import check_liveness, check_reasoning, check_tool_calling
from aigw_monitor.checks.result import CapabilityStatus, LivenessStatus
from aigw_monitor.config.loader import ResolvedTarget
from aigw_monitor.config.schema import CapabilitySpec

BASE = "https://gw.test/v1"
URL = f"{BASE}/chat/completions"


def _target() -> ResolvedTarget:
    return ResolvedTarget(
        organization="org",
        base_url=BASE,
        model="m",
        api_key=None,
        max_tokens=16,
        capabilities={
            "tool_calling": CapabilitySpec(enabled=True),
            "reasoning": CapabilitySpec(enabled=True),
        },
    )


@respx.mock
async def test_liveness_up():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})
    )
    async with OpenAICompatClient(BASE, None, 5) as client:
        res = await check_liveness(client, _target())
    assert res.status == LivenessStatus.UP
    assert res.latency_ms is not None


@respx.mock
async def test_liveness_down_on_5xx():
    respx.post(URL).mock(return_value=httpx.Response(503, text="unavailable"))
    async with OpenAICompatClient(BASE, None, 5) as client:
        res = await check_liveness(client, _target())
    assert res.status == LivenessStatus.DOWN
    assert res.http_status == 503


@respx.mock
async def test_liveness_error_on_network():
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    async with OpenAICompatClient(BASE, None, 5) as client:
        res = await check_liveness(client, _target())
    assert res.status == LivenessStatus.ERROR


@respx.mock
async def test_tool_calling_available():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"tool_calls": [{"id": "1", "function": {"name": "get"}}]}}
                ]
            },
        )
    )
    async with OpenAICompatClient(BASE, None, 5) as client:
        res = await check_tool_calling(client, _target())
    assert res.status == CapabilityStatus.AVAILABLE


@respx.mock
async def test_tool_calling_unavailable_when_text_only():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "21°C"}}]})
    )
    async with OpenAICompatClient(BASE, None, 5) as client:
        res = await check_tool_calling(client, _target())
    assert res.status == CapabilityStatus.UNAVAILABLE


@respx.mock
async def test_tool_calling_unavailable_on_400():
    respx.post(URL).mock(return_value=httpx.Response(400, text="tools not supported"))
    async with OpenAICompatClient(BASE, None, 5) as client:
        res = await check_tool_calling(client, _target())
    assert res.status == CapabilityStatus.UNAVAILABLE
    assert res.http_status == 400


@respx.mock
async def test_reasoning_available_via_reasoning_content():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "391", "reasoning_content": "17*23..."}}]},
        )
    )
    async with OpenAICompatClient(BASE, None, 5) as client:
        res = await check_reasoning(client, _target())
    assert res.status == CapabilityStatus.AVAILABLE


@respx.mock
async def test_reasoning_available_via_token_count():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "391"}}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 42}},
            },
        )
    )
    async with OpenAICompatClient(BASE, None, 5) as client:
        res = await check_reasoning(client, _target())
    assert res.status == CapabilityStatus.AVAILABLE


@respx.mock
async def test_reasoning_unavailable():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "391"}}]})
    )
    async with OpenAICompatClient(BASE, None, 5) as client:
        res = await check_reasoning(client, _target())
    assert res.status == CapabilityStatus.UNAVAILABLE
