"""Définition des métriques Prometheus et de l'app ASGI d'exposition.

Surface volontairement limitée au monitoring : labels ``org`` / ``model`` uniquement
(pas de ``base_url`` ni de secret).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import CollectorRegistry, Counter, Gauge, make_asgi_app

from ..checks.result import CapabilityStatus

if TYPE_CHECKING:
    from ..checks.runner import RunSummary

_RAN = (CapabilityStatus.AVAILABLE, CapabilityStatus.UNAVAILABLE)


class PrometheusMetrics:
    """Conteneur de métriques lié à un registre dédié."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        labels = ["org", "model"]

        self.up = Gauge(
            "aigw_model_up", "Modèle joignable (1) ou non (0)", labels, registry=self.registry
        )
        self.capability = Gauge(
            "aigw_model_capability_available",
            "Capacité disponible (1/0) ; absente si non testée (label capability)",
            ["org", "model", "capability"],
            registry=self.registry,
        )
        self.latency = Gauge(
            "aigw_model_check_latency_seconds",
            "Latence de la sonde liveness (s)",
            labels,
            registry=self.registry,
        )
        self.errors = Counter(
            "aigw_model_check_errors_total",
            "Nombre de checks en erreur",
            labels,
            registry=self.registry,
        )
        self.mismatch = Gauge(
            "aigw_model_capability_mismatch",
            "Dérive : capacité déclarée vraie mais observée indisponible (1/0)",
            ["org", "model", "capability"],
            registry=self.registry,
        )
        self.run_timestamp = Gauge(
            "aigw_check_run_timestamp_seconds",
            "Horodatage Unix du dernier cycle terminé",
            registry=self.registry,
        )
        self.run_duration = Gauge(
            "aigw_check_run_duration_seconds",
            "Durée du dernier cycle (s)",
            registry=self.registry,
        )

    def record(self, summary: RunSummary) -> None:
        for r in summary.results:
            self.up.labels(r.organization, r.model).set(1 if r.is_up else 0)

            for name, result in r.capabilities.items():
                if result.status in _RAN:
                    self.capability.labels(r.organization, r.model, name).set(
                        1 if result.status == CapabilityStatus.AVAILABLE else 0
                    )
                self.mismatch.labels(r.organization, r.model, name).set(
                    1 if name in r.mismatches else 0
                )

            if r.liveness.latency_ms is not None:
                self.latency.labels(r.organization, r.model).set(r.liveness.latency_ms / 1000.0)
            if r.has_error:
                self.errors.labels(r.organization, r.model).inc()

        self.run_timestamp.set(summary.finished_at.timestamp())
        self.run_duration.set(summary.duration_seconds)

    def asgi_app(self):
        return make_asgi_app(registry=self.registry)
