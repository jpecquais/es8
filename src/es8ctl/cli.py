"""CLI es8ctl : devices · capture · inspect · diff · patches · system · transform · apply · verify · check · export-bel · import-bel · sniff · read.

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
from .apply import DEFAULT_INTERVAL_S, DEFAULT_PAGE_GAP_S, DEVICE_PRECONDITION, check_changes, plan_changes
from . import transform as tf
from .routing import render as render_chain
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
    else:
        from .transfer import resolve_port

        resolved = resolve_port(port, ports)
        if resolved is None:
            typer.echo(json.dumps({"error": f"Port inconnu : {port}", "available": ports}))
            raise typer.Exit(code=1)
        port = resolved

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
            try:
                entry["loop_chain"] = render_chain(fields["loop_position"])
            except CodecError as exc:
                entry["loop_chain_error"] = str(exc)
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


transform_app = typer.Typer(
    help="Transformations en masse : produisent un JSON de changements pour `es8ctl apply`."
)
app.add_typer(transform_app, name="transform")


def _emit_changes(changes: dict, out: Path | None, summary: dict) -> None:
    """Changements sur stdout (ou --out), résumé lisible sur stderr."""
    text = json.dumps(changes, indent=2, ensure_ascii=False)
    if out is None:
        typer.echo(text)
    else:
        out.write_text(text + "\n", encoding="utf-8")
    typer.echo(json.dumps({**summary, "patches_changed": len(changes["patches"]),
                           "out": str(out) if out else "stdout"}, ensure_ascii=False), err=True)


def _load_base(base: Path):
    try:
        return load_dump(base)
    except (CodecError, ValueError) as exc:
        _fail(2, error=str(exc), base=str(base))


@transform_app.command("set")
def transform_set(
    assignments: list[str] = typer.Argument(..., help="champ=valeur ou champ[index]=valeur (ex. ctl_func[NUM_8]=BPM)."),
    base: Path = typer.Option(..., "--base", "-b", exists=True, readable=True, help="Dump de l'ES-8."),
    patches: str = typer.Option("all", "--patches", help="Sélection : all, 0-1..9-8, 0-1,2-3."),
    out: Path = typer.Option(None, "--out", "-o", help="Fichier de sortie (sinon stdout)."),
) -> None:
    """Affecte des valeurs à une sélection de patchs."""
    dump = _load_base(base)
    try:
        changes = tf.op_set(dump, tf.select_patches(dump, patches), assignments)
    except CodecError as exc:
        _fail(2, error=str(exc))
    _emit_changes(changes, out, {"op": "set", "assignments": assignments, "selection": patches})


@transform_app.command("swap-loops")
def transform_swap_loops(
    loop_a: str = typer.Argument(..., help="Loop (1-8, L1…L8, LV)."),
    loop_b: str = typer.Argument(..., help="Loop (1-8, L1…L8, LV)."),
    base: Path = typer.Option(..., "--base", "-b", exists=True, readable=True, help="Dump de l'ES-8."),
    patches: str = typer.Option("all", "--patches", help="Sélection : all, 0-1..9-8, 0-1,2-3."),
    out: Path = typer.Option(None, "--out", "-o", help="Fichier de sortie (sinon stdout)."),
) -> None:
    """Échange deux loops partout (interrupteurs, carry-over, cibles d'assign, chaîne)."""
    dump = _load_base(base)
    try:
        changes = tf.op_swap_loops(dump, tf.select_patches(dump, patches), loop_a, loop_b)
    except CodecError as exc:
        _fail(2, error=str(exc))
    _emit_changes(changes, out, {
        "op": "swap-loops", "loops": [loop_a, loop_b], "selection": patches,
    })


@transform_app.command("variants")
def transform_variants(
    source: str = typer.Argument(..., help="Patch source (ex. 0-8)."),
    into: str = typer.Option(..., "--into", help="Premier patch cible (ex. 10-1) ; les suivants sont consécutifs."),
    count: int = typer.Option(..., "--count", "-n", help="Nombre de variantes."),
    base: Path = typer.Option(..., "--base", "-b", exists=True, readable=True, help="Dump de l'ES-8."),
    seed: int = typer.Option(0, "--seed", help="Graine du tirage (résultat reproductible)."),
    prefix: str = typer.Option(None, "--prefix", help="Début du nom des variantes (défaut : nom de la source)."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Autoriser l'écrasement de patchs non vierges."),
    out: Path = typer.Option(None, "--out", "-o", help="Fichier de sortie (sinon stdout)."),
) -> None:
    """Copie un patch en N variantes aux ordres de loops tous différents."""
    dump = _load_base(base)
    try:
        changes = tf.op_variants(dump, source, into, count, seed=seed, prefix=prefix, overwrite=overwrite)
    except CodecError as exc:
        _fail(2, error=str(exc))
    _emit_changes(changes, out, {"op": "variants", "source": source, "into": into,
                                 "count": count, "seed": seed})


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
        DEFAULT_INTERVAL_S, "--interval",
        help="Délai entre les deux messages d'une page, en secondes (≥ 0,05, spec Roland).",
    ),
    page_gap: float = typer.Option(
        DEFAULT_PAGE_GAP_S, "--page-gap", help="Pause entre deux pages, en secondes (≥ 0,05)."
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
        "estimated_s": round(plan.duration_s(interval, page_gap), 1),
        "expected": str(expected),
    }
    if not plan.frames:
        _print_json({**report, "note": "Aucun changement effectif : rien à envoyer."})
        return
    if not write:
        _print_json({**report, "note": "Simulation : rien n'a été envoyé. Ajouter --write --port <port>.",
                     "precondition": DEVICE_PRECONDITION})
        return

    from .transfer import list_output_ports, send_frames

    from .transfer import resolve_port

    outputs = list_output_ports()
    port = resolve_port(port, outputs) if port is not None else None
    if port is None or port not in outputs:
        _fail(2, error="Port de sortie requis avec --write (voir es8ctl devices).",
              port=port, available=outputs)
    report["port"] = port
    report["backup"] = str(_backup(base, backup_dir))
    report["precondition"] = DEVICE_PRECONDITION
    typer.echo(f"Rappel : {DEVICE_PRECONDITION}", err=True)
    sent = 0

    def progress(n: int, total: int) -> None:
        nonlocal sent
        sent = n
        typer.echo(f"\r{n}/{total} message(s) envoyé(s)   ", err=True, nl=False)

    try:
        send_frames(port, plan.frames, interval_s=interval, on_frame=progress, page_gap_s=page_gap)
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
    notes = []
    system_ok = not result["system"].get("changes")
    if not system_ok:
        # current_num = patch sélectionné : change dès qu'on navigue, ce n'est
        # pas de la configuration. Seuls les autres champs comptent.
        before, after = (decode_system(load_dump(p).system) for p in (expected, actual))
        fields = sorted(k for k in before if before[k] != after[k])
        result["system"]["changed_fields"] = fields
        if fields == ["current_num"]:
            system_ok = True
            notes.append(f"current_num ignoré ({before['current_num']} → {after['current_num']}) : patch sélectionné.")
    match = not result["patches"] and system_ok and not missing
    _print_json({"match": match, "notes": notes, **result})
    if not match:
        raise typer.Exit(code=1)


@app.command()
def check(
    changes: Path = typer.Argument(..., exists=True, readable=True, help="Changements JSON."),
    actual: Path = typer.Argument(..., exists=True, readable=True, help="Dump capturé après écriture."),
) -> None:
    """Vérifie, patch par patch, que des changements sont présents dans un dump.

    Code 0 si tous sont appliqués, 1 sinon, 2 erreur.
    """
    try:
        result = check_changes(
            list(split_frames(actual.read_bytes())), json.loads(changes.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, CodecError, ValueError) as exc:
        _fail(2, error=str(exc))
    _print_json(result)
    if result["applied_count"] != result["total"]:
        raise typer.Exit(code=1)


@app.command("export-bel")
def export_bel_cmd(
    syx: Path = typer.Argument(..., exists=True, readable=True, help="Bulk dump complet (.syx)."),
    out: Path = typer.Option(..., "--out", "-o", help="Fichier .bel à écrire."),
) -> None:
    """Exporte un dump au format .bel de l'éditeur officiel BOSS."""
    from .bel import export_bel
    from .codec import frames_by_counter

    try:
        frames = list(split_frames(syx.read_bytes()))
        document, warnings = export_bel(load_dump(syx), frames_by_counter(frames))
    except (OSError, CodecError, ValueError) as exc:
        _fail(2, error=str(exc), file=str(syx))
    out.write_text(json.dumps(document), encoding="utf-8")
    _print_json({"bel": str(out), "patches": len(document["patch"]), "warnings": warnings})


@app.command("import-bel")
def import_bel_cmd(
    bel: Path = typer.Argument(..., exists=True, readable=True, help="Fichier .bel de l'éditeur."),
    base: Path = typer.Option(..., "--base", "-b", exists=True, readable=True, help="Dump actuel de l'ES-8."),
    out: Path = typer.Option(None, "--out", "-o", help="Changements JSON (sinon stdout)."),
) -> None:
    """Convertit un .bel en changements JSON pour `es8ctl apply` (différences avec la base)."""
    from .bel import import_bel

    try:
        changes, warnings = import_bel(json.loads(bel.read_text(encoding="utf-8")), load_dump(base))
    except (OSError, json.JSONDecodeError, CodecError, ValueError) as exc:
        _fail(2, error=str(exc), file=str(bel))
    _emit_changes(changes, out, {"op": "import-bel", "bel": str(bel),
                                 "system_changed": sorted(changes.get("system", {})),
                                 "warnings": warnings})


@app.command()
def sniff(
    editor: str = typer.Option(..., "--editor", help="Port côté éditeur (ex. session réseau rtpMIDI)."),
    device: str = typer.Option(..., "--device", help="Port côté ES-8 (ex. WIDI Jack Bluetooth)."),
    device_in: str = typer.Option(
        None, "--device-in", help="Port d'écoute de l'ES-8, s'il diffère de --device (ex. interface filaire)."
    ),
    out_dir: Path = typer.Option(Path("captures"), "--out", "-o", help="Répertoire du journal."),
    timeout: float = typer.Option(None, "--timeout", "-t", help="Durée en secondes (sinon Ctrl-C)."),
) -> None:
    """Relaie l'éditeur officiel ↔ ES-8 en journalisant chaque message (JSON Lines).

    Seuls les messages de l'éditeur sont transmis à l'ES-8. Ctrl-C pour arrêter.
    """
    from .sniff import relay
    from .transfer import list_output_ports

    from .transfer import resolve_port

    inputs, outputs = list_ports(), list_output_ports()
    editor_port = resolve_port(editor, inputs)
    if editor_port is None or editor_port not in outputs:
        _fail(2, error=f"Port éditeur introuvable en entrée/sortie : {editor}", inputs=inputs, outputs=outputs)
    device_out = resolve_port(device, outputs)
    device_listen = resolve_port(device_in or device, inputs)
    if device_out is None or device_listen is None:
        _fail(2, error="Port ES-8 introuvable.", inputs=inputs, outputs=outputs)
    editor, device = editor_port, device_out
    if editor == device:
        _fail(2, error="Les ports éditeur et ES-8 doivent être différents.")

    def show(direction: str, entry: dict) -> None:
        arrow = "→ ES-8 " if direction.startswith("editor") else "← ES-8 "
        typer.echo(f"{entry['t']:9.3f} {arrow}{entry['type']:<14} {entry['hex'][:60]}", err=True)

    typer.echo(f"Relais {editor} ⇄ ES-8 (envoi {device}, écoute {device_listen}) : connecter "
               "l'éditeur. Ctrl-C pour arrêter.", err=True)
    try:
        result = relay(editor, device, out_dir, timeout_s=timeout, on_message=show,
                       device_in_port=device_listen)
    except Exception as exc:  # surface explicite
        _fail(1, error=str(exc))
    _print_json(result.summary())


@app.command()
def read(
    port: str = typer.Option(..., "--port", "-p", help="Port de sortie vers l'ES-8 (ex. WIDI)."),
    port_in: str = typer.Option(None, "--port-in", help="Port d'écoute de l'ES-8, s'il diffère de --port."),
    patches: str = typer.Option("all", "--patches", help="Patchs à lire : all, none, 0-1..9-8, 0-1,2-3."),
    system: bool = typer.Option(True, "--system/--no-system", help="Lire aussi le bloc système."),
    out_dir: Path = typer.Option(Path("captures"), "--out", "-o", help="Répertoire de sortie."),
    chunk: int = typer.Option(8, "--chunk", help="Pages par requête (les pages manquantes sont redemandées seules)."),
) -> None:
    """Lit l'ES-8 à distance (RQ1), sans dump au panneau. Écrit un .syx partiel ou complet.

    Code 0 si tout est lu, 1 si des pages manquent malgré les relances, 2 erreur.
    """
    from .codec import PATCH_COUNT
    from .request import frames_to_syx, patch_page, read_pages
    from .transfer import list_output_ports, resolve_port

    outputs, inputs = list_output_ports(), list_ports()
    out_port = resolve_port(port, outputs)
    in_port = resolve_port(port_in or port, inputs)
    if out_port is None or in_port is None:
        _fail(2, error="Port introuvable.", inputs=inputs, outputs=outputs)
    if patches.strip().lower() == "none":
        indices = []
    elif patches.strip().lower() == "all":
        indices = list(range(PATCH_COUNT))
    else:
        try:
            from .codec import parse_patch_label

            indices = sorted({i for part in patches.split(",") for i in (
                range(parse_patch_label(part.split("..")[0].strip()),
                      parse_patch_label(part.split("..")[-1].strip()) + 1))})
        except CodecError as exc:
            _fail(2, error=str(exc))
    pages = (list(range(8)) if system else []) + [patch_page(i) for i in indices]
    if not pages:
        _fail(2, error="Rien à lire.")

    def progress(n: int, total: int) -> None:
        typer.echo(f"\r{n}/{total} message(s) reçu(s)   ", err=True, nl=False)

    typer.echo(f"Lecture de {len(pages)} page(s) : envoi {out_port}, écoute {in_port}.", err=True)
    try:
        frames, missing = read_pages(out_port, in_port, pages, chunk_pages=chunk, on_progress=progress)
    except Exception as exc:  # surface explicite
        _fail(2, error=str(exc))
    typer.echo("", err=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"read_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.syx"
    target.write_bytes(frames_to_syx(frames))
    labels = [("système " + str(p + 1)) if p < 8 else patch_label(p - 8) for p in missing]
    _print_json({"syx": str(target), "frames": len(frames), "pages_requested": len(pages),
                 "missing_pages": labels})
    if missing:
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
