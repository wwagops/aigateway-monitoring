"""Statuts et résultat d'une sonde."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class LivenessStatus(enum.StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class CapabilityStatus(enum.StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass
class ProbeResult:
    """Résultat d'une sonde unique (liveness ou capacité)."""

    status: LivenessStatus | CapabilityStatus
    latency_ms: float | None = None
    http_status: int | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def skipped(cls, kind: type[LivenessStatus] | type[CapabilityStatus]) -> ProbeResult:
        return cls(status=kind.SKIPPED)
