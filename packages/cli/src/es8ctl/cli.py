"""CLI es8ctl : devices · capture · inspect · diff · patches · system · transform · apply · verify · check · export-bel · import-bel · sniff · read · patch (select, rename, copy, exchange, init) · web.

Sortie JSON machine-first par défaut. Seule `apply --write` émet vers l'ES-8,
après validation complète et sauvegarde horodatée du dump de base.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import typer

from .capture import CaptureResult, inspect_file, list_ports, record
from es8core.codec import BULK_LAST_COUNTER, CodecError, parse_patch_label, patch_label, unpack_page
from es8core.diff import diff_files, load_dump
from es8core.patch import FIRMWARE, SCHEMA_VERSION, decode_patch, out_of_range
from es8core.system import decode_system, system_out_of_range
from es8core.apply import DEFAULT_INTERVAL_S, DEFAULT_PAGE_GAP_S, DEVICE_PRECONDITION, check_changes, plan_changes
from es8core import transform as tf
from es8core.routing import render as render_chain
from es8core.codec import split_frames

app = typer.Typer(
    add_completion=False,
    help="Open-source editor for the BOSS ES-8. Output is JSON; nothing is sent to the ES-8 without --write.",
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
    where = f"counter {counter}/{BULK_LAST_COUNTER}" if counter is not None else "not an ES-8 frame"
    typer.echo(f"\r{received} frame(s) received · {where}   ", err=True, nl=False)


@app.command()
def devices() -> None:
    """List the available MIDI input and output ports."""
    from .transfer import list_output_ports

    _print_json({"input_ports": list_ports(), "output_ports": list_output_ports()})


@app.command()
def capture(
    port: str = typer.Option(None, "--port", "-p", help="MIDI input port (asks if omitted)."),
    out_dir: Path = typer.Option(
        Path("captures"), "--out", "-o", help="Output directory for the dump."
    ),
    timeout: float = typer.Option(
        None, "--timeout", "-t", help="Capture duration in seconds (otherwise Ctrl-C)."
    ),
    auto_stop: bool = typer.Option(
        True,
        "--auto-stop/--no-auto-stop",
        help=f"Stop at the last bulk dump frame (counter {BULK_LAST_COUNTER}).",
    ),
) -> None:
    """Record incoming SysEx frames. Start it BEFORE triggering the bulk dump on the ES-8 panel.

    Progress goes to stderr, the JSON result to stdout.
    """
    ports = list_ports()
    if port is None:
        if not ports:
            typer.echo(json.dumps({"error": "No MIDI input port found."}))
            raise typer.Exit(code=1)
        for i, name in enumerate(ports):
            typer.echo(f"{i}: {name}", err=True)
        choice = typer.prompt("Port to listen to (number)", type=int)
        port = ports[choice]
    else:
        from .transfer import resolve_port

        resolved = resolve_port(port, ports)
        if resolved is None:
            typer.echo(json.dumps({"error": f"Unknown port: {port}", "available": ports}))
            raise typer.Exit(code=1)
        port = resolved

    try:
        typer.echo(f"Listening to {port}: trigger the bulk dump on the ES-8.", err=True)
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
            f"WARNING: {len(result.decode_errors)} invalid frame(s) "
            "(bytes lost in transit?). Dump again before using it.",
            err=True,
        )
        raise typer.Exit(code=2)


@app.command()
def inspect(
    syx: Path = typer.Argument(..., exists=True, readable=True),
    address_size: int = typer.Option(
        4, "--address-size", help="Assumed address size (3 or 4 bytes)."
    ),
) -> None:
    """Decode a .syx file offline."""
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
    a: Path = typer.Argument(..., exists=True, readable=True, help="Reference dump (.syx)."),
    b: Path = typer.Argument(..., exists=True, readable=True, help="Dump to compare (.syx)."),
) -> None:
    """Compare two bulk dumps: differences per patch, byte and bit.

    Exit code: 0 identical, 1 different, 2 error.
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
        None, "--patch", "-p", help="Patch to output (e.g. 0-1), repeatable. All by default."
    ),
) -> None:
    """Decode the patches of a bulk dump to JSON (keys and values as in .bel files)."""
    try:
        dump = load_dump(syx)
        wanted = sorted({parse_patch_label(p) for p in patch}) if patch else sorted(dump.patches)
        missing = [patch_label(i) for i in wanted if i not in dump.patches]
        if missing:
            raise CodecError(f"Patch(es) missing or incomplete in the dump: {', '.join(missing)}.")
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
    """Decode the system block of a bulk dump to JSON (keys as in .bel files)."""
    try:
        dump = load_dump(syx)
        if dump.system is None:
            raise CodecError(
                "No system block (frames 0-15): start the capture before the dump."
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
    help="Bulk changes: they output a changes JSON for `es8ctl apply`."
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
    assignments: list[str] = typer.Argument(..., help="field=value or field[index]=value (e.g. ctl_func[NUM_8]=BPM)."),
    base: Path = typer.Option(..., "--base", "-b", exists=True, readable=True, help="ES-8 dump."),
    patches: str = typer.Option("all", "--patches", help="Selection: all, 0-1..9-8, 0-1,2-3."),
    out: Path = typer.Option(None, "--out", "-o", help="Output file (otherwise stdout)."),
) -> None:
    """Set values on a selection of patches."""
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
    base: Path = typer.Option(..., "--base", "-b", exists=True, readable=True, help="ES-8 dump."),
    patches: str = typer.Option("all", "--patches", help="Selection: all, 0-1..9-8, 0-1,2-3."),
    out: Path = typer.Option(None, "--out", "-o", help="Output file (otherwise stdout)."),
) -> None:
    """Swap two loops everywhere (switches, carry-over, assign targets, chain)."""
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
    source: str = typer.Argument(..., help="Source patch (e.g. 0-8)."),
    into: str = typer.Option(..., "--into", help="First target patch (e.g. 10-1); the next ones follow."),
    count: int = typer.Option(..., "--count", "-n", help="Number of variants."),
    base: Path = typer.Option(..., "--base", "-b", exists=True, readable=True, help="ES-8 dump."),
    seed: int = typer.Option(0, "--seed", help="Random seed (reproducible result)."),
    prefix: str = typer.Option(None, "--prefix", help="Start of the variants' names (default: the source name)."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow overwriting patches that are not blank."),
    out: Path = typer.Option(None, "--out", "-o", help="Output file (otherwise stdout)."),
) -> None:
    """Copy a patch into N variants, each with a different loop order."""
    dump = _load_base(base)
    try:
        changes = tf.op_variants(dump, source, into, count, seed=seed, prefix=prefix, overwrite=overwrite)
    except CodecError as exc:
        _fail(2, error=str(exc))
    _emit_changes(changes, out, {"op": "variants", "source": source, "into": into,
                                 "count": count, "seed": seed})


@app.command()
def apply(
    changes: Path = typer.Argument(..., help="Changes JSON (\"-\" for stdin)."),
    base: Path = typer.Option(
        ..., "--base", "-b", exists=True, readable=True,
        help="Fresh dump of the ES-8 (current state), the base for the changes.",
    ),
    write: bool = typer.Option(False, "--write", help="Actually send to the ES-8 (otherwise a dry run)."),
    port: str = typer.Option(None, "--port", "-p", help="MIDI output port (required with --write)."),
    expected_out: Path = typer.Option(
        None, "--expected-out", help="Expected dump after writing (default: captures/expected_<timestamp>.syx)."
    ),
    backup_dir: Path = typer.Option(Path("backups"), "--backup-dir", help="Backup directory."),
    interval: float = typer.Option(
        DEFAULT_INTERVAL_S, "--interval",
        help="Delay between the two messages of a page, in seconds (≥ 0.05, Roland spec).",
    ),
    page_gap: float = typer.Option(
        DEFAULT_PAGE_GAP_S, "--page-gap", help="Pause between two pages, in seconds (≥ 0.05)."
    ),
    confirm: bool = typer.Option(
        False, "--confirm",
        help="After sending, read the written pages back (RQ1) and resend those that differ.",
    ),
    port_in: str = typer.Option(None, "--port-in", help="Input port for --confirm, if different from --port."),
    rounds: int = typer.Option(3, "--rounds", help="Maximum read-back / resend rounds, with --confirm."),
) -> None:
    """Apply changes to the ES-8. Dry run by default; --write to send.

    Exit codes: 0 success, 1 pages not confirmed despite resending
    (--confirm), 2 invalid changes or base, 3 write interrupted.
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
        _print_json({**report, "note": "Nothing actually changes: nothing to send."})
        return
    if not write:
        _print_json({**report, "note": "Dry run: nothing was sent. Add --write --port <port>.",
                     "precondition": DEVICE_PRECONDITION})
        return

    from .transfer import list_output_ports, send_frames

    from .transfer import resolve_port

    outputs = list_output_ports()
    port = resolve_port(port, outputs) if port is not None else None
    if port is None or port not in outputs:
        _fail(2, error="An output port is required with --write (see es8ctl devices).",
              port=port, available=outputs)
    report["port"] = port
    report["backup"] = str(_backup(base, backup_dir))
    report["precondition"] = DEVICE_PRECONDITION
    typer.echo(f"Reminder: {DEVICE_PRECONDITION}", err=True)
    sent = 0

    def progress(n: int, total: int) -> None:
        nonlocal sent
        sent = n
        typer.echo(f"\r{n}/{total} message(s) sent   ", err=True, nl=False)

    try:
        send_frames(port, plan.frames, interval_s=interval, on_frame=progress, page_gap_s=page_gap)
    except (KeyboardInterrupt, Exception) as exc:  # écriture partielle : toujours signalée
        typer.echo("", err=True)
        _fail(3, **report, error=f"Write interrupted: {exc!r}", sent=sent)
    typer.echo("", err=True)
    report["sent"] = sent
    if not confirm:
        _print_json({
            **report,
            "next_steps": [
                f"es8ctl read --port \"{port}\"",
                f"es8ctl verify {expected} captures/<new read>.syx",
            ],
        })
        return

    import asyncio

    import mido

    from es8core.session import MidoTransport, write_confirmed_async

    listen = resolve_port(port_in or port, list_ports())
    if listen is None:
        _fail(2, **report, error=f"Input port not found: {port_in or port}")
    def phase_progress(phase: str, n: int, total: int) -> None:
        typer.echo(f"\r{phase} {n}/{total}   ", err=True, nl=False)

    with mido.open_input(listen) as inp, mido.open_output(port) as out:
        for _ in inp.iter_pending():
            pass
        result = asyncio.run(write_confirmed_async(
            MidoTransport(inp, out), plan.frames, interval, page_gap, rounds, phase_progress,
            already_sent=True,
        ))
    typer.echo("", err=True)
    todo = result["pending_counters"]
    labels = sorted({patch_label(c // 2 - 8) if c >= 16 else "system" for c in todo})
    _print_json({**report, "confirmed": result["confirmed"], "confirm": result["history"],
                 "not_confirmed": labels})
    if todo:
        raise typer.Exit(code=1)


@app.command()
def verify(
    expected: Path = typer.Argument(..., exists=True, readable=True, help="Expected dump (from apply)."),
    actual: Path = typer.Argument(..., exists=True, readable=True, help="Dump read after writing."),
) -> None:
    """Check that a dump read after writing matches the expected one. Exit 0 if it does, 1 if not."""
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
            notes.append(f"current_num ignored ({before['current_num']} → {after['current_num']}): selected patch.")
    match = not result["patches"] and system_ok and not missing
    _print_json({"match": match, "notes": notes, **result})
    if not match:
        raise typer.Exit(code=1)


@app.command()
def check(
    changes: Path = typer.Argument(..., exists=True, readable=True, help="Changes JSON."),
    actual: Path = typer.Argument(..., exists=True, readable=True, help="Dump read after writing."),
) -> None:
    """Check, patch by patch, that changes are present in a dump.

    Exit 0 if all are applied, 1 if not, 2 on error.
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
    syx: Path = typer.Argument(..., exists=True, readable=True, help="Complete bulk dump (.syx)."),
    out: Path = typer.Option(..., "--out", "-o", help=".bel file to write."),
) -> None:
    """Export a dump as a .bel file (official BOSS editor librarian format)."""
    from es8core.bel import export_bel
    from es8core.codec import frames_by_counter

    try:
        frames = list(split_frames(syx.read_bytes()))
        document, warnings = export_bel(load_dump(syx), frames_by_counter(frames))
    except (OSError, CodecError, ValueError) as exc:
        _fail(2, error=str(exc), file=str(syx))
    out.write_text(json.dumps(document), encoding="utf-8")
    _print_json({"bel": str(out), "patches": len(document["patch"]), "warnings": warnings})


@app.command("import-bel")
def import_bel_cmd(
    bel: Path = typer.Argument(..., exists=True, readable=True, help=".bel file from the editor."),
    base: Path = typer.Option(..., "--base", "-b", exists=True, readable=True, help="Current ES-8 dump."),
    out: Path = typer.Option(None, "--out", "-o", help="Changes JSON (otherwise stdout)."),
) -> None:
    """Turn a .bel file into changes JSON for `es8ctl apply` (differences with the base)."""
    from es8core.bel import import_bel

    try:
        changes, warnings = import_bel(json.loads(bel.read_text(encoding="utf-8")), load_dump(base))
    except (OSError, json.JSONDecodeError, CodecError, ValueError) as exc:
        _fail(2, error=str(exc), file=str(bel))
    _emit_changes(changes, out, {"op": "import-bel", "bel": str(bel),
                                 "system_changed": sorted(changes.get("system", {})),
                                 "warnings": warnings})


@app.command()
def sniff(
    editor: str = typer.Option(..., "--editor", help="Port on the editor side (e.g. an rtpMIDI network session)."),
    device: str = typer.Option(..., "--device", help="Port on the ES-8 side (name or unique prefix, see es8ctl devices)."),
    device_in: str = typer.Option(
        None, "--device-in", help="Port to listen to the ES-8, if different from --device (e.g. a wired interface)."
    ),
    out_dir: Path = typer.Option(Path("captures"), "--out", "-o", help="Log directory."),
    timeout: float = typer.Option(None, "--timeout", "-t", help="Duration in seconds (otherwise Ctrl-C)."),
) -> None:
    """Relay the official editor ↔ ES-8, logging every message (JSON Lines).

    Only the editor's messages are forwarded to the ES-8. Ctrl-C to stop.
    """
    from .sniff import relay
    from .transfer import list_output_ports

    from .transfer import resolve_port

    inputs, outputs = list_ports(), list_output_ports()
    editor_port = resolve_port(editor, inputs)
    if editor_port is None or editor_port not in outputs:
        _fail(2, error=f"Editor port not found as input and output: {editor}", inputs=inputs, outputs=outputs)
    device_out = resolve_port(device, outputs)
    device_listen = resolve_port(device_in or device, inputs)
    if device_out is None or device_listen is None:
        _fail(2, error="ES-8 port not found.", inputs=inputs, outputs=outputs)
    editor, device = editor_port, device_out
    if editor == device:
        _fail(2, error="The editor and ES-8 ports must be different.")

    def show(direction: str, entry: dict) -> None:
        arrow = "→ ES-8 " if direction.startswith("editor") else "← ES-8 "
        typer.echo(f"{entry['t']:9.3f} {arrow}{entry['type']:<14} {entry['hex'][:60]}", err=True)

    typer.echo(f"Relaying {editor} ⇄ ES-8 (sending to {device}, listening to {device_listen}): connect "
               "the editor. Ctrl-C to stop.", err=True)
    try:
        result = relay(editor, device, out_dir, timeout_s=timeout, on_message=show,
                       device_in_port=device_listen)
    except Exception as exc:  # surface explicite
        _fail(1, error=str(exc))
    _print_json(result.summary())


@app.command()
def names(
    port: str = typer.Option(..., "--port", "-p", help="Output port to the ES-8 (name or unique prefix, see es8ctl devices)."),
    port_in: str = typer.Option(None, "--port-in", help="Port to listen to the ES-8, if different from --port."),
) -> None:
    """Read the 800 patch names (≈ 7 s) without reading the patches themselves.

    Output: {"0-1": "NAME", …}. Exit 0 if all 800 names were read, 1 if not, 2 on error.
    """
    from es8core.codec import PATCH_COUNT
    from es8core.request import read_names
    from .transfer import list_output_ports, resolve_port

    outputs, inputs = list_output_ports(), list_ports()
    out_port = resolve_port(port, outputs)
    in_port = resolve_port(port_in or port, inputs)
    if out_port is None or in_port is None:
        _fail(2, error="Port not found.", inputs=inputs, outputs=outputs)
    try:
        found = read_names(out_port, in_port)
    except Exception as exc:  # surface explicite
        _fail(2, error=str(exc))
    _print_json({patch_label(i): found[i].rstrip() for i in sorted(found)})
    if len(found) < PATCH_COUNT:
        raise typer.Exit(code=1)


@app.command()
def read(
    port: str = typer.Option(..., "--port", "-p", help="Output port to the ES-8 (name or unique prefix, see es8ctl devices)."),
    port_in: str = typer.Option(None, "--port-in", help="Port to listen to the ES-8, if different from --port."),
    patches: str = typer.Option("all", "--patches", help="Patches to read: all, none, 0-1..9-8, 0-1,2-3."),
    system: bool = typer.Option(True, "--system/--no-system", help="Also read the system block."),
    out_dir: Path = typer.Option(Path("captures"), "--out", "-o", help="Output directory."),
    chunk: int = typer.Option(8, "--chunk", help="Pages per request (missing pages are requested again one by one)."),
) -> None:
    """Read the ES-8 remotely (RQ1), with no panel action. Writes a partial or complete .syx.

    Exit 0 if everything was read, 1 if pages are still missing after retries, 2 on error.
    """
    from es8core.codec import PATCH_COUNT
    from es8core.request import frames_to_syx, patch_page, read_pages
    from .transfer import list_output_ports, resolve_port

    outputs, inputs = list_output_ports(), list_ports()
    out_port = resolve_port(port, outputs)
    in_port = resolve_port(port_in or port, inputs)
    if out_port is None or in_port is None:
        _fail(2, error="Port not found.", inputs=inputs, outputs=outputs)
    if patches.strip().lower() == "none":
        indices = []
    elif patches.strip().lower() == "all":
        indices = list(range(PATCH_COUNT))
    else:
        try:
            from es8core.codec import parse_patch_label

            indices = sorted({i for part in patches.split(",") for i in (
                range(parse_patch_label(part.split("..")[0].strip()),
                      parse_patch_label(part.split("..")[-1].strip()) + 1))})
        except CodecError as exc:
            _fail(2, error=str(exc))
    pages = (list(range(8)) if system else []) + [patch_page(i) for i in indices]
    if not pages:
        _fail(2, error="Nothing to read.")

    def progress(n: int, total: int) -> None:
        typer.echo(f"\r{n}/{total} message(s) received   ", err=True, nl=False)

    typer.echo(f"Reading {len(pages)} page(s): sending to {out_port}, listening to {in_port}.", err=True)
    try:
        frames, missing = read_pages(out_port, in_port, pages, chunk_pages=chunk, on_progress=progress)
    except Exception as exc:  # surface explicite
        _fail(2, error=str(exc))
    typer.echo("", err=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"read_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.syx"
    target.write_bytes(frames_to_syx(frames))
    labels = [("system " + str(p + 1)) if p < 8 else patch_label(p - 8) for p in missing]
    _print_json({"syx": str(target), "frames": len(frames), "pages_requested": len(pages),
                 "missing_pages": labels})
    if missing:
        raise typer.Exit(code=1)


patch_app = typer.Typer(
    help="Direct ES-8 commands (official editor protocol), each checked by reading back."
)
app.add_typer(patch_app, name="patch")


def _run_live(op, port: str, port_in: str | None, write: bool, backup_dir: Path) -> None:
    """Simulation, ou : sauvegarde des patchs touchés, envoi, relecture et vérification."""
    import time

    import mido

    from es8core.codec import patch_label as label_of
    from es8core.codec import split_dump
    from es8core.live import expected_after
    from es8core.patch import decode_patch
    from es8core.request import frames_to_syx, patch_page, read_pages
    from es8core.system import decode_system
    from .transfer import list_output_ports, resolve_port

    report = op.describe()
    if not write and op.action != "select":
        _print_json({**report, "mode": "dry-run", "note": "Add --write --port <port> to run it.",
                     "precondition": DEVICE_PRECONDITION})
        return
    out_port = resolve_port(port, list_output_ports()) if port else None
    in_port = resolve_port(port_in or port, list_ports()) if port else None
    if out_port is None or in_port is None:
        _fail(2, **report, error="Port not found (--port, --port-in).")

    def read_touched(indices, system=False):
        pages = (list(range(8)) if system else []) + [patch_page(i) for i in indices]
        frames, missing = read_pages(out_port, in_port, pages)
        if missing:
            _fail(1, **report, error="Read-back incomplete.", missing_pages=missing)
        return frames, split_dump(list(frames.values()))

    before = {}
    if op.touched:
        frames, dump = read_touched(op.touched)
        before = {i: dump.patches[i] for i in op.touched}
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup = backup_dir / f"backup_{stamp}_patch_{op.action}.syx"
        with backup.open("xb") as f:
            f.write(frames_to_syx(frames))
        report["backup"] = str(backup)
    with mido.open_output(out_port) as out:
        for message in op.messages:
            out.send(mido.Message.from_bytes(message))
            time.sleep(DEFAULT_INTERVAL_S)
    time.sleep(1.0)  # laisser l'ES-8 enregistrer

    if op.action == "select":
        _, dump = read_touched([], system=True)
        current = decode_system(dump.system)["current_num"]
        ok = label_of(current) == op.detail["patch"]
        report["current"] = label_of(current)
    else:
        _, dump = read_touched(op.touched)
        after = {i: dump.patches[i] for i in op.touched}
        names = {label_of(i): decode_patch(unpack_page(r))["name"] for i, r in after.items()}
        report["names_after"] = names
        expected = expected_after(op, before)
        if expected is not None:
            ok = after == expected
        elif op.action == "rename":
            ok = names[op.detail["patch"]] == op.detail["name"]
        else:  # initialize : patch d'usine au nom vide
            ok = names[op.detail["patch"]] == " " * 16
    _print_json({**report, "mode": "write", "confirmed": ok})
    if not ok:
        raise typer.Exit(code=1)


_PORT = typer.Option(None, "--port", "-p", help="Port to the ES-8 (name or unique prefix, see es8ctl devices).")
_PORT_IN = typer.Option(None, "--port-in", help="Input port, if different from --port.")
_WRITE = typer.Option(False, "--write", help="Run it (otherwise a dry run).")
_BACKUPS = typer.Option(Path("backups"), "--backup-dir", help="Backup directory.")


def _live(build, *args, port, port_in, write, backup_dir) -> None:
    from es8core import live

    try:
        op = getattr(live, build)(*args)
    except CodecError as exc:
        _fail(2, error=str(exc))
    _run_live(op, port, port_in, write, backup_dir)


@patch_app.command("select")
def patch_select(patch: str = typer.Argument(..., help="Patch to recall (e.g. 6-2)."),
                 port: str = _PORT, port_in: str = _PORT_IN) -> None:
    """Recall a patch on the ES-8 (no data changes)."""
    _live("select", patch, port=port, port_in=port_in, write=True, backup_dir=Path("backups"))


@patch_app.command("rename")
def patch_rename(patch: str = typer.Argument(...), name: str = typer.Argument(..., help="16 characters at most."),
                 port: str = _PORT, port_in: str = _PORT_IN, write: bool = _WRITE,
                 backup_dir: Path = _BACKUPS) -> None:
    """Rename a patch."""
    _live("rename", patch, name, port=port, port_in=port_in, write=write, backup_dir=backup_dir)


@patch_app.command("copy")
def patch_copy(source: str = typer.Argument(...), target: str = typer.Argument(...),
               port: str = _PORT, port_in: str = _PORT_IN, write: bool = _WRITE,
               backup_dir: Path = _BACKUPS) -> None:
    """Copy a patch onto another (the target is overwritten)."""
    _live("copy", source, target, port=port, port_in=port_in, write=write, backup_dir=backup_dir)


@patch_app.command("exchange")
def patch_exchange(first: str = typer.Argument(...), second: str = typer.Argument(...),
                   port: str = _PORT, port_in: str = _PORT_IN, write: bool = _WRITE,
                   backup_dir: Path = _BACKUPS) -> None:
    """Swap two patches."""
    _live("exchange", first, second, port=port, port_in=port_in, write=write, backup_dir=backup_dir)


@patch_app.command("init")
def patch_init(patch: str = typer.Argument(...), port: str = _PORT, port_in: str = _PORT_IN,
               write: bool = _WRITE, backup_dir: Path = _BACKUPS) -> None:
    """Reset a patch (factory settings, blank name)."""
    _live("initialize", patch, port=port, port_in=port_in, write=write, backup_dir=backup_dir)


def _engine_sources() -> list[Path]:
    import es8core

    root = Path(es8core.__file__).resolve().parent
    return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]


def library_zip() -> bytes:
    """Le moteur es8core (sources .py) en zip, pour Pyodide dans le navigateur."""
    import io
    import zipfile

    import es8core

    root = Path(es8core.__file__).resolve().parent
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _engine_sources():
            archive.write(path, Path("es8core") / path.relative_to(root))
    return buffer.getvalue()


def _web_roots() -> dict[str, Path]:
    """Dossiers du site : applis (web/) et accueil (site/), installés ou dans le dépôt."""
    here = Path(__file__).resolve().parent
    for base in (here, here.parents[3]):  # paquet installé, puis dépôt (packages/cli/src/es8ctl)
        web, site = base / "web", base / "site"
        if (web / "shared" / "engine.js").is_file():
            return {"web": web, "site": site}
    raise FileNotFoundError("Web apps not found (web/shared/engine.js).")


ZIP_PATH = "shared/es8core.zip"


def _lan_address() -> str:
    """Adresse de cette machine sur le réseau local (une socket UDP « connectée » n'envoie rien)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
        except OSError:
            return socket.gethostname()


@app.command()
def web(
    port: int = typer.Option(8765, "--port", help="Local HTTP port."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the browser."),
    lan: bool = typer.Option(False, "--lan", help="Also serve on the local network (another computer or a tablet on the "
                             "same Wi-Fi). Plain HTTP: browsers give Web MIDI only to https or localhost."),
) -> None:
    """Run the web apps locally (Chrome / Edge: Web MIDI). Ctrl-C to stop."""
    import functools
    import http.server
    import webbrowser

    roots = _web_roots()
    # Le moteur est refait dès qu'une source change : un serveur lancé la veille sert le code du jour.
    engine = {"key": None, "zip": b""}

    def archive() -> bytes:
        sources = _engine_sources()
        key = (len(sources), max((p.stat().st_mtime_ns for p in sources), default=0))
        if key != engine["key"]:
            engine.update(key=key, zip=library_zip())
        return engine["zip"]

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (API http.server)
            if self.path.split("?")[0] == "/" + ZIP_PATH:
                data = archive()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            super().do_GET()

        def translate_path(self, path):
            # /control/…, /shared/… → web/ ; le reste (accueil) → site/
            clean = path.split("?")[0].lstrip("/")
            first = clean.split("/")[0]
            base = roots["web"] if (roots["web"] / first).is_dir() and first else roots["site"]
            return str(base / clean)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, *args):
            pass

    handler = functools.partial(Handler, directory=str(roots["site"]))
    server = http.server.ThreadingHTTPServer(("0.0.0.0" if lan else "127.0.0.1", port), handler)
    url = f"http://localhost:{port}/control/"
    typer.echo(f"Web editor: {url}  (Chrome or Edge; Ctrl-C to stop)", err=True)
    if lan:
        typer.echo(f"On the network: http://{_lan_address()}:{port}/control/", err=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


@app.command("build-web")
def build_web(
    out: Path = typer.Option(Path("dist/site"), "--out", "-o", help="Directory of the site to build."),
) -> None:
    """Build the web apps and the home page as a static site (GitHub Pages or any HTTPS host).

    Everything runs in the browser: the site needs no application server.
    Web MIDI requires HTTPS (or localhost).
    """
    roots = _web_roots()
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(roots["site"], out)
    for app_dir in sorted(p for p in roots["web"].iterdir() if p.is_dir()):
        shutil.copytree(app_dir, out / app_dir.name, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    (out / ZIP_PATH).write_bytes(library_zip())
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    if owner:  # publication GitHub : l'adresse de l'image Docker est connue
        home = out / "index.html"
        home.write_text(home.read_text(encoding="utf-8").replace("&lt;owner&gt;", owner.lower()), encoding="utf-8")
    (out / ".nojekyll").write_text("")  # GitHub Pages : servir les fichiers tels quels
    _print_json({"site": str(out), "files": sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())})


def main() -> None:
    app()


if __name__ == "__main__":
    main()

