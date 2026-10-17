"""CLI es8ctl : devices · capture · inspect · diff.

Sortie JSON machine-first par défaut. Read-only : aucune de ces commandes
n'émet quoi que ce soit vers l'ES-8.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .capture import CaptureResult, inspect_file, list_ports, record
from .codec import CodecError
from .diff import diff_files

app = typer.Typer(
    add_completion=False,
    help="Éditeur open-source pour le Boss ES-8. Read-only tant qu'il n'existe pas de sous-commande d'écriture.",
)


def _print_json(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _dump_result(result: CaptureResult) -> dict:
    return {
        "syx": str(result.syx_path),
        "sidecar": str(result.json_path),
        "frame_count": result.frame_count,
        "ignored_message_count": result.ignored_count,
        "decode_errors": result.decode_errors,
    }


@app.command()
def devices() -> None:
    """Liste les ports d'entrée MIDI disponibles."""
    _print_json({"input_ports": list_ports()})


@app.command()
def capture(
    port: str = typer.Option(None, "--port", "-p", help="Port d'entrée MIDI (interactif si omis)."),
    out_dir: Path = typer.Option(
        Path("captures"), "--out", "-o", help="Répertoire de sortie du dump."
    ),
    timeout: float = typer.Option(
        None, "--timeout", "-t", help="Durée de capture en secondes (sinon Ctrl-C)."
    ),
) -> None:
    """Enregistre les trames SysEx reçues. Déclencher le bulk dump au panneau de l'ES-8."""
    ports = list_ports()
    if port is None:
        if not ports:
            typer.echo(json.dumps({"error": "Aucun port d'entrée MIDI détecté."}))
            raise typer.Exit(code=1)
        for i, name in enumerate(ports):
            typer.echo(f"{i}: {name}", err=True)
        choice = typer.prompt("Port à écouter (numéro)", type=int)
        port = ports[choice]
    elif port not in ports:
        typer.echo(
            json.dumps({"error": f"Port inconnu : {port}", "available": ports})
        )
        raise typer.Exit(code=1)

    try:
        result = record(port, Path(out_dir), timeout_s=timeout)
    except Exception as exc:  # surface explicite : jamais d'échec silencieux
        typer.echo(json.dumps({"error": str(exc), "port": port}))
        raise typer.Exit(code=1) from exc

    _print_json(_dump_result(result))
    if result.decode_errors:
        raise typer.Exit(code=2)


@app.command()
def inspect(
    syx: Path = typer.Argument(..., exists=True, readable=True),
    address_size: int = typer.Option(
        4, "--address-size", help="Taille d'adresse supposée (3 ou 4 octets)."
    ),
) -> None:
    """Re-décode hors ligne un fichier .syx."""
    try:
        result = inspect_file(syx, address_size=address_size)
    except (CodecError, ValueError) as exc:
        typer.echo(json.dumps({"error": str(exc), "file": str(syx)}))
        raise typer.Exit(code=2) from exc
    _print_json(result)
    if result["decode_errors"]:
        raise typer.Exit(code=2)


@app.command()
def diff(
    a: Path = typer.Argument(..., exists=True, readable=True, help="Dump de référence (.syx)."),
    b: Path = typer.Argument(..., exists=True, readable=True, help="Dump à comparer (.syx)."),
) -> None:
    """Compare deux bulk dumps : écarts par patch, octet et bit.

    Code de sortie : 0 identiques, 1 différents, 2 erreur.
    """
    try:
        result = diff_files(a, b)
    except (CodecError, ValueError) as exc:
        typer.echo(json.dumps({"error": str(exc), "a": str(a), "b": str(b)}))
        raise typer.Exit(code=2) from exc
    _print_json(result)
    if result["changed"]:
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
