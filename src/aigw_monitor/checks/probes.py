"""Sondes fonctionnelles : liveness, tool calling, reasoning.

Chaque sonde fait un **appel réel** de complétion et mappe la réponse vers un statut.
Les messages d'erreur sont assainis (base_url masquée, troncature) car ils peuvent
transiter par l'API / les logs.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config.loader import ResolvedTarget
from .client import OpenAICompatClient
from .result import CapabilityStatus, LivenessStatus, ProbeResult

_MAX_ERROR_LEN = 300
TOOL_MAX_TOKENS = 128
REASONING_MAX_TOKENS = 256

# Outil factice utilisé pour tester le tool calling.
WEATHER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_current_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        },
    },
}


def _sanitize(message: str, base_url: str) -> str:
    cleaned = message.replace(base_url, "<endpoint>") if base_url else message
    if len(cleaned) > _MAX_ERROR_LEN:
        cleaned = cleaned[:_MAX_ERROR_LEN] + "…"
    return cleaned


def _short_body(response: httpx.Response, base_url: str) -> str:
    try:
        text = response.text
    except Exception:  # pragma: no cover - défensif
        return f"HTTP {response.status_code}"
    return _sanitize(f"HTTP {response.status_code}: {text}", base_url)


def _first_message(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices") or []
    if not choices:
        return {}
    message = choices[0].get("message") or {}
    return message if isinstance(message, dict) else {}


async def check_liveness(client: OpenAICompatClient, target: ResolvedTarget) -> ProbeResult:
    payload = {
        "model": target.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    try:
        response, latency = await client.chat_completion(payload)
    except httpx.TimeoutException as exc:
        return ProbeResult(
            LivenessStatus.ERROR, error=_sanitize(f"timeout: {exc}", client.base_url)
        )
    except httpx.HTTPError as exc:
        return ProbeResult(
            LivenessStatus.ERROR, error=_sanitize(f"http error: {exc}", client.base_url)
        )

    if response.status_code != 200:
        return ProbeResult(
            LivenessStatus.DOWN,
            latency_ms=latency,
            http_status=response.status_code,
            error=_short_body(response, client.base_url),
        )
    try:
        data = response.json()
    except ValueError:
        return ProbeResult(
            LivenessStatus.DOWN, latency_ms=latency, http_status=200, error="réponse JSON invalide"
        )
    if data.get("choices"):
        return ProbeResult(LivenessStatus.UP, latency_ms=latency, http_status=200)
    return ProbeResult(
        LivenessStatus.DOWN, latency_ms=latency, http_status=200, error="aucune choice renvoyée"
    )


async def check_tool_calling(client: OpenAICompatClient, target: ResolvedTarget) -> ProbeResult:
    spec = target.capabilities.get("tool_calling")
    payload: dict[str, Any] = {
        "model": target.model,
        "messages": [
            {
                "role": "user",
                "content": "What is the current weather in Paris? Use the available tool.",
            }
        ],
        "tools": [WEATHER_TOOL],
        "tool_choice": "auto",
        "max_tokens": max(target.max_tokens, TOOL_MAX_TOKENS),
        "temperature": 0,
    }
    if spec is not None:
        payload.update(spec.extra_body)

    try:
        response, latency = await client.chat_completion(payload)
    except httpx.HTTPError as exc:
        return ProbeResult(
            CapabilityStatus.ERROR, error=_sanitize(f"http error: {exc}", client.base_url)
        )

    if response.status_code == 200:
        message = _first_message(response.json() if _is_json(response) else {})
        tool_calls = message.get("tool_calls")
        if tool_calls:
            return ProbeResult(
                CapabilityStatus.AVAILABLE,
                latency_ms=latency,
                http_status=200,
                details={"tool_calls": len(tool_calls)},
            )
        return ProbeResult(
            CapabilityStatus.UNAVAILABLE,
            latency_ms=latency,
            http_status=200,
            error="réponse sans tool_calls",
        )

    # Beaucoup de gateways renvoient 400 quand l'outil n'est pas supporté.
    if response.status_code == 400:
        return ProbeResult(
            CapabilityStatus.UNAVAILABLE,
            latency_ms=latency,
            http_status=400,
            error=_short_body(response, client.base_url),
        )
    return ProbeResult(
        CapabilityStatus.ERROR,
        latency_ms=latency,
        http_status=response.status_code,
        error=_short_body(response, client.base_url),
    )


async def check_reasoning(client: OpenAICompatClient, target: ResolvedTarget) -> ProbeResult:
    spec = target.capabilities.get("reasoning")
    payload: dict[str, Any] = {
        "model": target.model,
        "messages": [
            {"role": "user", "content": "Think step by step, then answer: what is 17 * 23?"}
        ],
        "max_tokens": max(target.max_tokens, REASONING_MAX_TOKENS),
        "temperature": 0,
    }
    if spec is not None:
        payload.update(spec.extra_body)

    try:
        response, latency = await client.chat_completion(payload)
    except httpx.HTTPError as exc:
        return ProbeResult(
            CapabilityStatus.ERROR, error=_sanitize(f"http error: {exc}", client.base_url)
        )

    if response.status_code != 200:
        return ProbeResult(
            CapabilityStatus.ERROR,
            latency_ms=latency,
            http_status=response.status_code,
            error=_short_body(response, client.base_url),
        )

    data = response.json() if _is_json(response) else {}
    message = _first_message(data)
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    reasoning_tokens = (
        (data.get("usage") or {}).get("completion_tokens_details") or {}
    ).get("reasoning_tokens")

    if (isinstance(reasoning, str) and reasoning.strip()) or (reasoning_tokens or 0) > 0:
        return ProbeResult(
            CapabilityStatus.AVAILABLE,
            latency_ms=latency,
            http_status=200,
            details={"reasoning_tokens": reasoning_tokens},
        )
    return ProbeResult(
        CapabilityStatus.UNAVAILABLE,
        latency_ms=latency,
        http_status=200,
        error="aucun reasoning_content / reasoning_tokens",
    )


def _is_json(response: httpx.Response) -> bool:
    try:
        response.json()
        return True
    except ValueError:
        return False
