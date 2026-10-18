"""CLI es8ctl : devices · capture · inspect · diff · patches · system · apply · verify.

Sortie JSON machine-first par défaut. Seule `apply --write` émet vers l'ES-8,
après validation complète et sauvegarde horodatée du dump de base.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import typer

from .capture import CaptureResult, inspect_file, list_ports, record
from .codec import BULK_LAST_COUNTER, CodecError, parse_patch_label, patch_label, unpack_page
from .diff import diff_files, load_dump
from .patch import FIRMWARE, SCHEMA_VERSION, decode_patch, out_of_range
from .system import decode_system, system_out_of_range
from .apply import DEFAULT_INTERVAL_S, plan_changes
from .codec import split_frames

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
    """Liste les ports MIDI d'entrée et de sortie disponibles."""
    from .transfer import list_output_ports

    _print_json({"input_ports": list_ports(), "output_ports": list_output_ports()})


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
        typer.echo(
            f"ATTENTION : {len(result.decode_errors)} trame(s) invalide(s) "
            "(octets perdus en transit ?) — refaire le dump avant de s'en servir.",
            err=True,
        )
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
        None, "--patch", "-p", help="Patch à sortir (ex. 0-1), répétable. Tous par défaut."
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


def _fail(code: int, **payload) -> None:
    typer.echo(json.dumps(payload, default=str))
    raise typer.Exit(code=code)


def _backup(base: Path, backup_dir: Path) -> Path:
    """Copie horodatée du dump de base ; ne remplace jamais un fichier existant."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"backup_{stamp}_{base.name}"
    with base.open("rb") as src, target.open("xb") as dst:  # « x » : échec si existe
        shutil.copyfileobj(src, dst)
    return target


@app.command()
def apply(
    changes: Path = typer.Argument(..., help="Changements JSON (« - » pour stdin)."),
    base: Path = typer.Option(
        ..., "--base", "-b", exists=True, readable=True,
        help="Dump frais de l'ES-8 (état actuel), base des modifications.",
    ),
    write: bool = typer.Option(False, "--write", help="Envoyer réellement à l'ES-8 (sinon simulation)."),
    port: str = typer.Option(None, "--port", "-p", help="Port de sortie MIDI (requis avec --write)."),
    expected_out: Path = typer.Option(
        None, "--expected-out", help="Dump attendu après écriture (défaut : captures/expected_<horodatage>.syx)."
    ),
    backup_dir: Path = typer.Option(Path("backups"), "--backup-dir", help="Répertoire des sauvegardes."),
    interval: float = typer.Option(
        DEFAULT_INTERVAL_S, "--interval", help="Délai entre messages en secondes (≥ 0,05, spec Roland)."
    ),
) -> None:
    """Applique des changements à l'ES-8. Simulation par défaut ; --write pour envoyer.

    Codes de sortie : 0 succès, 2 changements ou base invalides, 3 écriture
    interrompue (partielle).
    """
    try:
        raw = sys.stdin.read() if str(changes) == "-" else changes.read_text(encoding="utf-8")
        plan = plan_changes(list(split_frames(base.read_bytes())), json.loads(raw))
    except (OSError, json.JSONDecodeError, CodecError, ValueError) as exc:
        _fail(2, error=str(exc), base=str(base))

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    expected = expected_out or Path("captures") / f"expected_{stamp}.syx"
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.write_bytes(plan.expected)
    report = {
        "mode": "write" if write else "dry-run",
        "base": str(base),
        "changes": plan.changes,
        "frames": len(plan.frames),
        "estimated_s": round(plan.duration_s(interval), 1),
        "expected": str(expected),
    }
    if not plan.frames:
        _print_json({**report, "note": "Aucun changement effectif : rien à envoyer."})
        return
    if not write:
        _print_json({**report, "note": "Simulation : rien n'a été envoyé. Ajouter --write --port <port>."})
        return

    from .transfer import list_output_ports, send_frames

    outputs = list_output_ports()
    if port is None or port not in outputs:
        _fail(2, error="Port de sortie requis avec --write (voir es8ctl devices).",
              port=port, available=outputs)
    report["port"] = port
    report["backup"] = str(_backup(base, backup_dir))
    sent = 0

    def progress(n: int, total: int) -> None:
        nonlocal sent
        sent = n
        typer.echo(f"\r{n}/{total} message(s) envoyé(s)   ", err=True, nl=False)

    try:
        send_frames(port, plan.frames, interval_s=interval, on_frame=progress)
    except (KeyboardInterrupt, Exception) as exc:  # écriture partielle : toujours signalée
        typer.echo("", err=True)
        _fail(3, **report, error=f"Écriture interrompue : {exc!r}", sent=sent)
    typer.echo("", err=True)
    _print_json({
        **report,
        "sent": sent,
        "next_steps": [
            "es8ctl capture  (puis déclencher le bulk dump au panneau)",
            f"es8ctl verify {expected} captures/<nouveau dump>.syx",
        ],
    })


@app.command()
def verify(
    expected: Path = typer.Argument(..., exists=True, readable=True, help="Dump attendu (apply)."),
    actual: Path = typer.Argument(..., exists=True, readable=True, help="Dump capturé après écriture."),
) -> None:
    """Vérifie qu'un dump capturé correspond au dump attendu. Code 0 si conforme, 1 sinon."""
    try:
        result = diff_files(expected, actual)
    except (CodecError, ValueError) as exc:
        _fail(2, error=str(exc))
    missing = result["coverage"]["only_in_a"]
    match = not result["changed"] and not missing
    _print_json({"match": match, **result})
    if not match:
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
