"""Relais MIDI enregistreur entre l'éditeur officiel et l'ES-8 (étape 4 du plan).

Le Mac s'intercale : l'éditeur (Windows, via rtpMIDI / session réseau) parle
au port `editor`, l'ES-8 est sur le port `device` (WIDI). Chaque message est
retransmis tel quel dans l'autre sens et journalisé (JSON Lines, une ligne
par message, écrite et vidée aussitôt : rien n'est perdu sur Ctrl-C).

But : capturer la commande de lecture non documentée que l'éditeur envoie
à la connexion, et les messages d'édition en temps réel.

Ce module émet du MIDI vers l'ES-8, mais uniquement ce que l'éditeur
officiel envoie lui-même : il n'invente aucun message.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

EDITOR_TO_DEVICE = "editor->es8"
DEVICE_TO_EDITOR = "es8->editor"
ECHO = "es8-echo"  # écho THRU d'un message de l'éditeur : journalisé, non retransmis
ECHO_WINDOW_S = 1.0


@dataclass
class SniffResult:
    log_path: Path
    counts: Counter = field(default_factory=Counter)

    def summary(self) -> dict:
        return {"log": str(self.log_path), "messages": dict(self.counts)}


def _describe(msg) -> dict:
    raw = bytes(msg.bytes())
    entry = {"type": msg.type, "size": len(raw), "hex": raw.hex(" ")}
    if msg.type == "sysex" and len(raw) >= 9 and raw[1] == 0x41:
        entry["roland"] = {"command": f"{raw[7]:02x}", "after_command": raw[8:-1].hex(" ")}
    return entry


def relay(
    editor_port: str,
    device_port: str,
    log_dir: Path,
    timeout_s: float | None = None,
    on_message: Callable[[str, dict], None] | None = None,
    device_in_port: str | None = None,
    drop_echo: bool = True,
) -> SniffResult:
    """Relaie et journalise jusqu'à Ctrl-C (ou `timeout_s`).

    `device_in_port` : port d'écoute de l'ES-8 s'il diffère du port d'envoi
    (ex. envoi par le WIDI, réception par une interface filaire sur la MIDI
    OUT de l'ES-8 — le WIDI répond lui-même aux requêtes d'identité).

    `drop_echo` : en « MIDI Out Mode : THRU », l'ES-8 renvoie ce qu'il reçoit
    sur sa MIDI OUT ; l'éditeur, voyant revenir ses propres messages, échoue
    (« MIDI Connection error »). Un message de l'ES-8 identique à un message
    de l'éditeur envoyé dans la seconde précédente n'est donc pas retransmis
    (il reste journalisé, sens « es8-echo »).
    """
    import mido

    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    result = SniffResult(log_path=log_dir / f"sniff_{stamp}.jsonl")
    start = time.monotonic()
    try:
        with (
            mido.open_input(editor_port) as from_editor,
            mido.open_output(editor_port) as to_editor,
            mido.open_input(device_in_port or device_port) as from_device,
            mido.open_output(device_port) as to_device,
            result.log_path.open("w", encoding="utf-8") as log,
        ):
            routes = ((from_editor, to_device, EDITOR_TO_DEVICE), (from_device, to_editor, DEVICE_TO_EDITOR))
            recent: list[tuple[float, bytes]] = []  # messages récents de l'éditeur (détection d'écho)
            while timeout_s is None or time.monotonic() - start < timeout_s:
                idle = True
                for source, sink, direction in routes:
                    msg = source.poll()
                    if msg is None:
                        continue
                    idle = False
                    now = time.monotonic()
                    raw = bytes(msg.bytes())
                    if direction == EDITOR_TO_DEVICE:
                        recent.append((now, raw))
                    recent[:] = [(t, r) for t, r in recent if now - t < ECHO_WINDOW_S]
                    is_echo = (
                        drop_echo and direction == DEVICE_TO_EDITOR and any(r == raw for _, r in recent)
                    )
                    if is_echo:
                        recent.remove(next((t, r) for t, r in recent if r == raw))
                        direction = ECHO
                    else:
                        sink.send(msg)  # retransmission d'abord : latence minimale
                    entry = {"t": round(now - start, 4), "dir": direction, **_describe(msg)}
                    log.write(json.dumps(entry) + "\n")
                    log.flush()
                    result.counts[direction] += 1
                    if on_message is not None:
                        on_message(direction, entry)
                if idle:
                    time.sleep(0.001)
    except KeyboardInterrupt:
        pass
    return result
