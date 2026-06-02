"""CLI (typer) : run / check-once / validate-config."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer

from .checks.capabilities import CAPABILITY_NAMES, selected_probes
from .checks.result import CapabilityStatus, LivenessStatus
from .checks.runner import ModelCheckResult, RunSummary, run_cycle
from .config.loader import ResolvedTarget, load_config
from .logging import configure_logging
from .settings import Settings

app = typer.Typer(
    add_completion=False,
    help="Monitoring de serveurs d'inférence compatibles OpenAI.",
)

_CONFIG_OPTION = typer.Option(
    None, "--config", "-c", help="Chemin du fichier YAML (def. config.yaml ou $AIGW_CONFIG_PATH)."
)


def _build_settings(config: Path | None) -> Settings:
    if config is not None:
        os.environ["AIGW_CONFIG_PATH"] = str(config)
    return Settings()


@app.command()
def run(config: Path | None = _CONFIG_OPTION) -> None:
    """Démarre le daemon (scheduler + API REST + /metrics)."""
    settings = _build_settings(config)
    from .service import run_service

    asyncio.run(run_service(settings))


@app.command("check-once")
def check_once(
    config: Path | None = _CONFIG_OPTION,
    store: bool = typer.Option(True, help="Persister le cycle en base."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Afficher les logs détaillés (INFO) sur stderr."
    ),
) -> None:
    """Exécute un seul cycle de checks et affiche un résumé."""
    settings = _build_settings(config)
    configure_logging("INFO" if verbose else "WARNING")
    loaded = load_config(settings.config_path)
    summary = asyncio.run(_run_once(settings, loaded.targets, store=store))
    _print_summary(summary)


@app.command("validate-config")
def validate_config(config: Path | None = _CONFIG_OPTION) -> None:
    """Valide le YAML et liste les cibles avec les sondes sélectionnées."""
    settings = _build_settings(config)
    configure_logging("WARNING")
    loaded = load_config(settings.config_path)
    typer.secho(
        f"{len(loaded.organizations)} organisation(s) · {len(loaded.targets)} cible(s)\n",
        bold=True,
    )
    org_w, mdl_w = _col_widths(loaded.targets)
    typer.secho(f"  {'ORGANISATION':<{org_w}}  {'MODÈLE':<{mdl_w}}  SONDES", bold=True)
    for t in loaded.targets:
        org = _truncate(t.organization, org_w).ljust(org_w)
        mdl = _truncate(t.model, mdl_w).ljust(mdl_w)
        typer.echo(f"  {org}  {mdl}  {', '.join(selected_probes(t))}")


async def _run_once(settings: Settings, targets: list, store: bool) -> RunSummary:
    session_factory = None
    engine = None
    if store:
        from .db.base import create_all_if_sqlite, make_engine, make_session_factory

        engine = make_engine(settings.database_url)
        await create_all_if_sqlite(engine)  # SQLite local : crée le schéma au besoin
        session_factory = make_session_factory(engine)
    try:
        return await run_cycle(
            targets=targets,
            settings=settings,
            session_factory=session_factory,
            trigger="manual",
        )
    finally:
        if engine is not None:
            await engine.dispose()


_STATUS_COLOR = {
    "UP": typer.colors.GREEN,
    "AVAILABLE": typer.colors.GREEN,
    "DOWN": typer.colors.RED,
    "UNAVAILABLE": typer.colors.YELLOW,
    "ERROR": typer.colors.BRIGHT_RED,
}


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _col_widths(items: list[ResolvedTarget] | list[ModelCheckResult]) -> tuple[int, int]:
    org_w = min(max((len(i.organization) for i in items), default=12), 24)
    org_w = max(org_w, len("ORGANISATION"))
    mdl_w = min(max((len(i.model) for i in items), default=12), 30)
    mdl_w = max(mdl_w, len("MODÈLE"))
    return org_w, mdl_w


def _status_cell(status: LivenessStatus | CapabilityStatus, width: int) -> str:
    if status.value == "SKIPPED":
        return typer.style("—".ljust(width), dim=True)
    text = status.value.ljust(width)
    color = _STATUS_COLOR.get(status.value)
    return typer.style(text, fg=color) if color else text


def _print_summary(summary: RunSummary) -> None:
    results = sorted(summary.results, key=lambda r: (r.organization, r.model))
    head = (
        f"Cycle terminé — {summary.total} cible(s) · {summary.up} up · "
        f"{summary.errors} erreur(s) · {summary.duration_seconds:.1f}s"
    )
    if summary.run_id is not None:
        head += f" · run_id={summary.run_id}"
    typer.echo()
    typer.secho(head, bold=True)
    typer.echo()

    if not results:
        typer.secho("  (aucune cible)", dim=True)
        return

    org_w, mdl_w = _col_widths(summary.results)
    cap_w = {name: max(len(name), len("UNAVAILABLE")) for name in CAPABILITY_NAMES}

    header = f"  {'ORGANISATION':<{org_w}}  {'MODÈLE':<{mdl_w}}  {'LIVENESS':<8}"
    for name in CAPABILITY_NAMES:
        header += f"  {name:<{cap_w[name]}}"
    header += f"  {'LAT.':>7}"
    typer.secho(header, bold=True)

    for r in results:
        org = _truncate(r.organization, org_w).ljust(org_w)
        mdl = _truncate(r.model, mdl_w).ljust(mdl_w)
        latency = f"{r.liveness.latency_ms:.0f}ms" if r.liveness.latency_ms is not None else "—"
        row = f"  {org}  {mdl}  {_status_cell(r.liveness.status, 8)}"
        for name in CAPABILITY_NAMES:
            result = r.capabilities.get(name)
            status = result.status if result is not None else CapabilityStatus.SKIPPED
            row += f"  {_status_cell(status, cap_w[name])}"
        row += f"  {latency:>7}"
        if r.mismatches:
            drift = typer.style(f"⚠ dérive: {', '.join(r.mismatches)}", fg=typer.colors.YELLOW)
            row += f"  {drift}"
        typer.echo(row)

    typer.echo()
    typer.secho(
        "  Légende : UP/AVAILABLE = ok · DOWN/UNAVAILABLE = indisponible · "
        "ERROR = erreur · — = non testé",
        dim=True,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
