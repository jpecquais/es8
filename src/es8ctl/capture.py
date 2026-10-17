"""Écoute MIDI et enregistrement de dump SysEx.

Read-only : ce module n'émet jamais rien vers l'ES-8. Il écoute, écrit
les trames SysEx reçues dans un fichier `.syx` brut et un sidecar JSON de
métadonnées avec les en-têtes décodés.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .codec import CodecError, parse_frame, split_frames


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def list_ports() -> list[str]:
    """Liste les ports d'entrée MIDI disponibles."""
    import mido

    return list(mido.get_input_names())


@dataclass
class CaptureResult:
    syx_path: Path
    json_path: Path
    frame_count: int
    ignored_count: int
    decode_errors: list[str]


def record(
    port: str,
    out_dir: Path,
    timeout_s: float | None = None,
    address_size: int = 4,
) -> CaptureResult:
    """Écoute `port` et enregistre toutes les trames SysEx reçues.

    Seules les messages SysEx sont conservés ; tout le reste est compté
    dans `ignored_count`. Chaque trame est écrite dans le `.syx` dès sa
    réception : un arrêt brutal (crash, Ctrl-C) ne perd jamais ce qui a
    déjà été reçu. Se termine sur KeyboardInterrupt (Ctrl-C) ou après
    `timeout_s` secondes si fourni.
    """
    import time

    import mido

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    syx_path = out_dir / f"dump_{stamp}.syx"
    json_path = out_dir / f"dump_{stamp}.json"
    started = _now_iso()
    frames: list[bytes] = []
    ignored = 0

    try:
        with mido.open_input(port) as inp, syx_path.open("wb") as sink:
            deadline = None if timeout_s is None else time.monotonic() + timeout_s
            while True:
                msg = inp.poll()
                if msg is not None:
                    if msg.type == "sysex":
                        frame = bytes([0xF0, *msg.data, 0xF7])
                        sink.write(frame)
                        frames.append(frame)
                    else:
                        ignored += 1
                elif deadline is not None and time.monotonic() >= deadline:
                    break
                else:
                    time.sleep(0.01)
    except KeyboardInterrupt:
        pass  # Ctrl-C : finalisation normale, le .syx est déjà complet.

    return _save(
        frames,
        ignored,
        port=port,
        started=started,
        address_size=address_size,
        syx_path=syx_path,
        json_path=json_path,
    )


def _save(
    frames: list[bytes],
    ignored: int,
    port: str,
    started: str,
    address_size: int,
    syx_path: Path,
    json_path: Path,
) -> CaptureResult:
    # Le .syx a été écrit incrémentalement pendant la capture ; on ne
    # fait que vérifier son état final.
    if not frames and not syx_path.exists():
        syx_path.write_bytes(b"")

    decoded_frames = []
    errors: list[str] = []
    for index, frame in enumerate(frames):
        entry: dict = {"index": index, "size": len(frame), "hex": frame.hex(" ")}
        try:
            msg = parse_frame(frame, address_size=address_size)
            entry["decoded"] = {
                "device_id": msg.device_id,
                "model_id": msg.model_id,
                "command": {0x11: "RQ1", 0x12: "DT1"}.get(msg.command, hex(msg.command)),
                "address": "".join(f"{b:02X}" for b in msg.address),
                "data_size": len(msg.data),
                "checksum_valid": msg.checksum_valid,
            }
        except CodecError as exc:
            entry["error"] = str(exc)
            errors.append(f"trame {index}: {exc}")
        decoded_frames.append(entry)

    sidecar = {
        "tool": "es8ctl",
        "format_version": 1,
        "created": _now_iso(),
        "capture_started": started,
        "port": port,
        "address_size_assumed": address_size,
        "note": (
            "address_size est une hypothèse (4 par défaut, matériel Roland récent) ; "
            "le hex brut permet un re-décodage sans perte."
        ),
        "frame_count": len(frames),
        "ignored_message_count": ignored,
        "frames": decoded_frames,
    }
    json_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")

    return CaptureResult(
        syx_path=syx_path,
        json_path=json_path,
        frame_count=len(frames),
        ignored_count=ignored,
        decode_errors=errors,
    )


def inspect_file(syx_path: Path, address_size: int = 4) -> dict:
    """Re-décode hors ligne un fichier .syx, sans matériel."""
    raw = Path(syx_path).read_bytes()
    if not raw:
        raise ValueError(f"Fichier vide : {syx_path}")

    frames = []
    errors = []
    frame_list = list(split_frames(raw))
    for index, frame in enumerate(frame_list):
        entry = {"index": index, "size": len(frame), "hex": frame.hex(" ")}
        try:
            msg = parse_frame(frame, address_size=address_size)
            entry["decoded"] = {
                "device_id": msg.device_id,
                "model_id": msg.model_id,
                "command": {0x11: "RQ1", 0x12: "DT1"}.get(msg.command, hex(msg.command)),
                "address": "".join(f"{b:02X}" for b in msg.address),
                "data_size": len(msg.data),
                "checksum_valid": msg.checksum_valid,
            }
        except CodecError as exc:
            entry["error"] = str(exc)
            errors.append(f"trame {index}: {exc}")
        frames.append(entry)

    return {
        "file": str(syx_path),
        "size": len(raw),
        "frame_count": len(frame_list),
        "address_size_assumed": address_size,
        "decode_errors": errors,
        "frames": frames,
    }
