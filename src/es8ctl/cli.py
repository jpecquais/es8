"""CLI es8ctl : devices · capture · inspect · diff · patches · system.

Sortie JSON machine-first par défaut. Read-only : aucune de ces commandes
n'émet quoi que ce soit vers l'ES-8.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .capture import CaptureResult, inspect_file, list_ports, record
from .codec import BULK_LAST_COUNTER, CodecError, parse_patch_label, patch_label, unpack_page
from .diff import diff_files, load_dump
from .patch import FIRMWARE, SCHEMA_VERSION, decode_patch, out_of_range
from .system import decode_system, system_out_of_range

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


def _progress(received: int, counter: int | None) -> None:
    where = f"compteur {counter}/{BULK_LAST_COUNTER}" if counter is not None else "trame non ES-8"
    typer.echo(f"\r{received} trame(s) reçue(s) · {where}   ", err=True, nl=False)


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
    auto_stop: bool = typer.Option(
        True,
        "--auto-stop/--no-auto-stop",
        help=f"S'arrêter à la dernière trame du bulk dump (compteur {BULK_LAST_COUNTER}).",
    ),
) -> None:
    """Enregistre les trames SysEx reçues. Lancer AVANT de déclencher le bulk dump au panneau.

    La progression s'affiche sur stderr ; le résultat JSON sur stdout.
    """
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
        typer.echo(f"Écoute de {port} : déclencher le bulk dump sur l'ES-8.", err=True)
        result = record(
            port, Path(out_dir), timeout_s=timeout, auto_stop=auto_stop, on_frame=_progress
        )
        typer.echo("", err=True)
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


@app.command()
def patches(
    syx: Path = typer.Argument(..., exists=True, readable=True, help="Bulk dump (.syx)."),
    patch: list[str] = typer.Option(
        None, "--patch", "-p", help="Patch à sortir (ex. 1-1), répétable. Tous par défaut."
    ),
) -> None:
    """Décode les patchs d'un bulk dump en JSON (forme des clés et valeurs alignée sur le .bel)."""
    try:
        dump = load_dump(syx)
        wanted = sorted({parse_patch_label(p) for p in patch}) if patch else sorted(dump.patches)
        missing = [patch_label(i) for i in wanted if i not in dump.patches]
        if missing:
            raise CodecError(f"Patch(s) absent(s) ou incomplet(s) dans le dump : {', '.join(missing)}.")
        decoded = []
        for i in wanted:
            fields = decode_patch(unpack_page(dump.patches[i]))
            entry = {"patch": patch_label(i), "index": i, **fields}
            warnings = out_of_range(fields)
            if warnings:
                entry["warnings"] = warnings
            decoded.append(entry)
    except (CodecError, ValueError) as exc:
        typer.echo(json.dumps({"error": str(exc), "file": str(syx)}))
        raise typer.Exit(code=2) from exc
    _print_json(
        {
            "tool": "es8ctl",
            "schema_version": SCHEMA_VERSION,
            "source": str(syx),
            "system_present": dump.system is not None,
            "incomplete": [patch_label(i) for i in dump.incomplete],
            "firmware": FIRMWARE,
            "patches": decoded,
        }
    )


@app.command()
def system(
    syx: Path = typer.Argument(..., exists=True, readable=True, help="Bulk dump (.syx)."),
) -> None:
    """Décode le bloc système d'un bulk dump en JSON (clés alignées sur le .bel)."""
    try:
        dump = load_dump(syx)
        if dump.system is None:
            raise CodecError(
                "Bloc système absent (trames 0-15) : lancer la capture avant le dump."
            )
        fields = decode_system(dump.system)
    except (CodecError, ValueError) as exc:
        typer.echo(json.dumps({"error": str(exc), "file": str(syx)}))
        raise typer.Exit(code=2) from exc
    payload = {
        "tool": "es8ctl",
        "schema_version": SCHEMA_VERSION,
        "source": str(syx),
        "firmware": FIRMWARE,
        "system": fields,
    }
    warnings = system_out_of_range(fields)
    if warnings:
        payload["warnings"] = warnings
    _print_json(payload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
