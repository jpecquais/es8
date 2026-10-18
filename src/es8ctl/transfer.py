"""Envoi de trames SysEx vers l'ES-8 — le seul module qui émet du MIDI.

Appelé uniquement par `es8ctl apply --write`. Respecte la spec Roland :
les trames d'une page partent à la suite, dans l'ordre, avec un délai
minimal entre deux messages.
"""

from __future__ import annotations

import time
from typing import Callable

from .apply import DEFAULT_INTERVAL_S

MIN_INTERVAL_S = 0.05  # spec Roland


def list_output_ports() -> list[str]:
    import mido

    return list(mido.get_output_names())


def send_frames(
    port: str,
    frames: list[bytes],
    interval_s: float = DEFAULT_INTERVAL_S,
    on_frame: Callable[[int, int], None] | None = None,
) -> int:
    """Envoie les trames dans l'ordre ; rend le nombre de trames envoyées.

    Une interruption (Ctrl-C, erreur) en cours d'envoi remonte telle quelle :
    l'appelant doit signaler que l'écriture est partielle.
    """
    if interval_s < MIN_INTERVAL_S:
        raise ValueError(f"Intervalle {interval_s} s < {MIN_INTERVAL_S} s exigé par la spec Roland.")
    import mido

    sent = 0
    with mido.open_output(port) as out:
        for frame in frames:
            if sent:
                time.sleep(interval_s)
            out.send(mido.Message("sysex", data=frame[1:-1]))
            sent += 1
            if on_frame is not None:
                on_frame(sent, len(frames))
    return sent
