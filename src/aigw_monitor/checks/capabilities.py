"""Registre des capacités sondables — **point d'extension unique**.

Pour ajouter une capacité de modèle :
  1. écrire une sonde ``check_x(client, target) -> ProbeResult`` dans ``probes.py`` ;
  2. l'enregistrer dans ``CAPABILITY_PROBES`` ci-dessous.

Rien d'autre à toucher : le runner, le stockage (JSONB), les métriques (label ``capability``),
l'API et la CLU itèrent ce registre dynamiquement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..config.loader import ResolvedTarget
from .client import OpenAICompatClient
from .probes import check_reasoning, check_tool_calling
from .result import ProbeResult

ProbeFn = Callable[[OpenAICompatClient, ResolvedTarget], Awaitable[ProbeResult]]

# ───────────────────────── Registre (clé = nom de capacité) ─────────────────────────
CAPABILITY_PROBES: dict[str, ProbeFn] = {
    "tool_calling": check_tool_calling,
    "reasoning": check_reasoning,
}
# ─────────────────────────────────────────────────────────────────────────────────────

#: Noms de capacités sondables, dans l'ordre d'affichage.
CAPABILITY_NAMES: tuple[str, ...] = tuple(CAPABILITY_PROBES)


def _is_enabled(target: ResolvedTarget, name: str) -> bool:
    spec = target.capabilities.get(name)
    return spec is not None and spec.enabled


def selected_probes(target: ResolvedTarget) -> list[str]:
    """Sondes à exécuter : liveness (toujours) + capacités déclarées qui ont une sonde."""
    return ["liveness", *(name for name in CAPABILITY_NAMES if _is_enabled(target, name))]


def unsupported_enabled(target: ResolvedTarget) -> list[str]:
    """Capacités activées en config mais sans sonde enregistrée (ignorées au runtime)."""
    return [name for name in target.enabled_capabilities if name not in CAPABILITY_PROBES]
