"""Envoi de trames SysEx vers l'ES-8 — le seul module qui émet du MIDI.

Appelé uniquement par `es8ctl apply --write`. Respecte la spec Roland :
les trames d'une page partent à la suite, dans l'ordre, avec un délai
minimal entre deux messages.

Rythme : les deux messages d'une page partent à `interval_s` d'écart (la
spec exige ≥ 50 ms et un envoi « consécutif » de la page), puis une pause
`page_gap_s` précède la page suivante (0,5 s validé sur 44 pages via WIDI).

Précondition côté appareil (apply.DEVICE_PRECONDITION) : l'ES-8 ignore tout
bulk dump reçu tant qu'il est sur l'écran Utility > Bulk Dump. Aucun
message d'erreur : seule la vérification par re-dump le révèle.
"""

from __future__ import annotations

import time
from typing import Callable

from .apply import DEFAULT_INTERVAL_S, DEFAULT_PAGE_GAP_S
from .codec import PATCH_FRAMES

MIN_INTERVAL_S = 0.05  # spec Roland


def list_output_ports() -> list[str]:
    import mido

    return list(mido.get_output_names())


def send_frames(
    port: str,
    frames: list[bytes],
    interval_s: float = DEFAULT_INTERVAL_S,
    on_frame: Callable[[int, int], None] | None = None,
    page_gap_s: float = DEFAULT_PAGE_GAP_S,
) -> int:
    """Envoie les trames dans l'ordre ; rend le nombre de trames envoyées.

    Une interruption (Ctrl-C, erreur) en cours d'envoi remonte telle quelle :
    l'appelant doit signaler que l'écriture est partielle.
    """
    if interval_s < MIN_INTERVAL_S or page_gap_s < MIN_INTERVAL_S:
        raise ValueError(f"Délai < {MIN_INTERVAL_S} s exigé par la spec Roland.")
    if len(frames) % PATCH_FRAMES:
        raise ValueError("Nombre de trames impair : une page incomplète serait rejetée.")
    import mido

    sent = 0
    with mido.open_output(port) as out:
        for frame in frames:
            if sent:
                time.sleep(page_gap_s if sent % PATCH_FRAMES == 0 else interval_s)
            out.send(mido.Message("sysex", data=frame[1:-1]))
            sent += 1
            if on_frame is not None:
                on_frame(sent, len(frames))
    return sent


def _fix_mojibake(name: str) -> str:
    """CoreMIDI via rtmidi rend parfois l'UTF-8 lu en Mac Roman : « R√©seau » → « Réseau »."""
    try:
        return name.encode("mac_roman").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def resolve_port(name: str, available: list[str]) -> str | None:
    """Port réel correspondant à `name` : exact, corrigé de l'encodage, ou préfixe unique."""
    if name in available:
        return name
    wanted = name.casefold()
    fixed = {port: _fix_mojibake(port).casefold() for port in available}
    exact = [port for port, f in fixed.items() if f == wanted]
    if len(exact) == 1:
        return exact[0]
    prefix = [port for port, f in fixed.items() if f.startswith(wanted)]
    return prefix[0] if len(prefix) == 1 else None
