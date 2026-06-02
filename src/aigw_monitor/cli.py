"""CLI (typer) : run / check-once / validate-config."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .checks.capabilities import CAPABILITY_NAMES, selected_probes
from .checks.probes import liveness_name
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
        # Nomme la sonde up/down (chat_completion / list_models) comme une capacité.
        probes = [liveness_name(t.liveness) if p == "liveness" else p for p in selected_probes(t)]
        typer.echo(f"  {org}  {mdl}  {', '.join(probes)}")


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


def _fmt_request(req: dict) -> str:
    """Essentiel de la requête envoyée (log d'entrée), pour affichage compact."""
    parts: list[str] = []
    if req.get("endpoint"):
        parts.append(req["endpoint"])
    prompt = req.get("prompt")
    if prompt:
        parts.append(f'prompt="{prompt if len(prompt) <= 60 else prompt[:60] + "…"}"')
    if req.get("tools"):
        parts.append(f"tools={req['tools']}")
    if req.get("tool_choice"):
        parts.append(f"tool_choice={req['tool_choice']}")
    if req.get("extra_body"):
        parts.append(f"extra_body={req['extra_body']}")
    return " · ".join(parts)


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _col_widths(items: list[ResolvedTarget] | list[ModelCheckResult]) -> tuple[int, int]:
    org_w = min(max((len(i.organization) for i in items), default=12), 24)
    org_w = max(org_w, len("ORGANISATION"))
    mdl_w = min(max((len(i.model) for i in items), default=12), 30)
    mdl_w = max(mdl_w, len("MODÈLE"))
    return org_w, mdl_w


def _fmt_lat(latency_ms: float | None) -> str:
    return f"{latency_ms:.0f}ms" if latency_ms is not None else "—"


def _cell(status: LivenessStatus | CapabilityStatus, latency_ms: float | None, width: int) -> str:
    """Cellule colorée : « statut latence » du test (ou '—' si non testé)."""
    if status.value == "SKIPPED":
        return typer.style("—".ljust(width), dim=True)
    text = f"{status.value} {_fmt_lat(latency_ms)}".ljust(width)
    color = _STATUS_COLOR.get(status.value)
    return typer.style(text, fg=color) if color else text


_RICH_STYLE = {
    "UP": "green",
    "AVAILABLE": "green",
    "DOWN": "red",
    "UNAVAILABLE": "yellow",
    "ERROR": "bright_red",
}


def _rich_cell(status: LivenessStatus | CapabilityStatus, latency_ms: float | None) -> Text:
    if status.value == "SKIPPED":
        return Text("—", style="dim")
    return Text(f"{status.value} {_fmt_lat(latency_ms)}", style=_RICH_STYLE.get(status.value, ""))


def _print_table_rich(results: list[ModelCheckResult]) -> None:
    """Tableau bordé (filets pleins) + couleurs — utilisé en terminal (TTY)."""
    table = Table(show_header=True, header_style="bold", show_lines=True, box=box.SQUARE)
    for col in ("ORGANISATION", "MODÈLE", "LIVENESS", *CAPABILITY_NAMES, "dérive"):
        table.add_column(col, no_wrap=True, overflow="fold")
    for r in results:
        cells = [Text(r.organization), Text(r.model)]
        cells.append(_rich_cell(r.liveness.status, r.liveness.latency_ms))
        for name in CAPABILITY_NAMES:
            res = r.capabilities.get(name)
            status = res.status if res is not None else CapabilityStatus.SKIPPED
            cells.append(_rich_cell(status, res.latency_ms if res is not None else None))
        cells.append(Text(", ".join(r.mismatches), style="yellow") if r.mismatches else Text(""))
        table.add_row(*cells)
    Console().print(table)


def _print_table_plain(results: list[ModelCheckResult]) -> None:
    """Tableau aligné par espaces (sans bordures) — pipe-friendly, utilisé hors TTY."""
    org_w, mdl_w = _col_widths(results)
    live_w = 13
    cap_w = {name: max(len(name), 19) for name in CAPABILITY_NAMES}  # « UNAVAILABLE 30000ms »
    header = f"  {'ORGANISATION':<{org_w}}  {'MODÈLE':<{mdl_w}}  {'LIVENESS':<{live_w}}"
    for name in CAPABILITY_NAMES:
        header += f"  {name:<{cap_w[name]}}"
    typer.secho(header, bold=True)
    for r in results:
        org = _truncate(r.organization, org_w).ljust(org_w)
        mdl = _truncate(r.model, mdl_w).ljust(mdl_w)
        row = f"  {org}  {mdl}  {_cell(r.liveness.status, r.liveness.latency_ms, live_w)}"
        for name in CAPABILITY_NAMES:
            res = r.capabilities.get(name)
            status = res.status if res is not None else CapabilityStatus.SKIPPED
            lat = res.latency_ms if res is not None else None
            row += f"  {_cell(status, lat, cap_w[name])}"
        if r.mismatches:
            drift = typer.style(f"⚠ dérive: {', '.join(r.mismatches)}", fg=typer.colors.YELLOW)
            row += f"  {drift}"
        typer.echo(row)


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

    # Tableau bordé + couleurs en terminal ; aligné par espaces (pipe-friendly) sinon.
    if sys.stdout.isatty():
        _print_table_rich(results)
    else:
        _print_table_plain(results)

    typer.echo()
    typer.secho(
        "  Légende : « statut latence » par test · UP/AVAILABLE = ok · "
        "DOWN/UNAVAILABLE = indisponible · ERROR = erreur · — = non testé",
        dim=True,
    )

    # Détails par sonde : l'essentiel de l'entrée (↳ requête envoyée) pour TOUTES les sondes
    # exécutées (y compris OK), + la sortie (statut/HTTP/erreur) pour les non-OK.
    typer.echo()
    typer.secho("  Détails par sonde (↳ = requête envoyée) :", bold=True)
    # Largeur d'étiquette : la sonde up/down est nommée comme une capacité (chat_completion/…).
    label_w = max(len("chat_completion"), *(len(n) for n in CAPABILITY_NAMES))
    for r in results:
        executed = [(r.liveness_name, r.liveness, r.liveness.status == LivenessStatus.UP)]
        for name in CAPABILITY_NAMES:
            res = r.capabilities.get(name)
            if res is None or res.status == CapabilityStatus.SKIPPED:
                continue
            executed.append((name, res, res.status == CapabilityStatus.AVAILABLE))

        typer.secho(f"  [{r.organization}] {r.model}", fg=typer.colors.CYAN)
        for name, res, ok in executed:
            sent = typer.style(_fmt_request(res.request), dim=True)
            if ok:
                typer.echo(f"      {name:<{label_w}} ↳ {sent}")
                continue
            http = f" HTTP {res.http_status}" if res.http_status is not None else ""
            msg = (res.error or "").strip().replace("\n", " ")
            if len(msg) > 140:
                msg = msg[:140] + "…"
            head = typer.style(f"{res.status.value}{http}", fg=_STATUS_COLOR.get(res.status.value))
            typer.echo(f"      {name:<{label_w}} {head}" + (f" : {msg}" if msg else ""))
            typer.echo(f"      {'':<{label_w}} ↳ {sent}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
