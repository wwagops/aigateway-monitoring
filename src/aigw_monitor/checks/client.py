"""Client HTTP minimal pour endpoints compatibles OpenAI (httpx async)."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

import httpx


class OpenAICompatClient:
    """Wrapper httpx pour ``POST {base_url}/chat/completions``.

    ``base_url`` inclut déjà le suffixe ``/v1`` (tel que déclaré en config).
    On construit des URL absolues pour éviter les pièges de jointure de httpx.
    """

    def __init__(self, base_url: str, api_key: str | None, timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._chat_url = f"{self._base_url}/chat/completions"
        self._models_url = f"{self._base_url}/models"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(headers=headers, timeout=timeout)

    @property
    def base_url(self) -> str:
        return self._base_url

    async def chat_completion(self, payload: dict[str, Any]) -> tuple[httpx.Response, float]:
        """Envoie la requête, renvoie (réponse, latence_ms). Peut lever httpx.HTTPError."""
        start = time.perf_counter()
        response = await self._client.post(self._chat_url, json=payload)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return response, latency_ms

    async def list_models(self) -> tuple[httpx.Response, float]:
        """GET {base_url}/models, renvoie (réponse, latence_ms). Peut lever httpx.HTTPError."""
        start = time.perf_counter()
        response = await self._client.get(self._models_url)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return response, latency_ms

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OpenAICompatClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
