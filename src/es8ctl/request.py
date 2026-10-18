"""Lecture de l'ES-8 à distance (RQ1), sans déclencher le dump au panneau.

Protocole établi à partir du code de l'éditeur officiel (es_midi.js) puis
vérifié sur l'appareil :

- mode éditeur : DT1 à l'ID 7F 50, données 00 01 (activer) / 00 00 (désactiver) ;
- requête : `F0 41 dev 00 00 00 14 11 <ID MSB> <ID LSB> <n MSB> <n LSB> <somme> F7`
  demande les messages de bulk ID … ID + n (bornes incluses) ; l'ES-8 répond
  par ces messages, au format exact du bulk dump.

Particularité du bloc système (constatée sur l'appareil) : toute requête qui
touche les messages 0-15 renvoie le bloc depuis le message 0, et la borne de
fin y est exclue (0..15 rend 0..14 ; 0..16 rend 0..16). Le système se lit
donc avec la requête 0..16.

Une réponse peut perdre des messages (interface filaire qui retient ou
perd la fin d'une rafale) : chaque page incomplète est redemandée seule.
Les échos THRU de nos propres messages sont ignorés.

Ce module n'envoie que des requêtes de lecture et la bascule du mode
éditeur, toujours désactivé en sortie.
"""

from __future__ import annotations

import time
from typing import Callable

from .codec import (
    BULK_LAST_COUNTER,
    PATCH_FIRST_COUNTER,
    PATCH_FRAMES,
    is_es8_bulk_frame,
    parse_es8_bulk_frame,
)
from .codec.roland import CMD_DT1, CMD_RQ1, checksum

MODEL = (0x00, 0x00, 0x00, 0x14)
EDITOR_MODE_ID = (0x7F, 0x50)
DEFAULT_CHUNK_PAGES = 8
DEFAULT_IDLE_S = 2.0
DEFAULT_RETRIES = 3
SYSTEM_LAST_ID = PATCH_FIRST_COUNTER - 1  # 15
SYSTEM_REQUEST = (0, PATCH_FIRST_COUNTER)  # 0..16 : seule forme qui rend les 16 messages système


def _sysex(command: int, body: list[int], device_id: int = 0x00) -> bytes:
    return bytes([0xF0, 0x41, device_id, *MODEL, command, *body, checksum(body), 0xF7])


def editor_mode_message(on: bool) -> bytes:
    return _sysex(CMD_DT1, [*EDITOR_MODE_ID, 0x00, 0x01 if on else 0x00])


def request_message(first_id: int, last_id: int) -> bytes:
    """RQ1 des messages first_id … last_id (inclus), comme l'éditeur officiel."""
    if not 0 <= first_id <= last_id <= BULK_LAST_COUNTER:
        raise ValueError(f"Plage de messages invalide : {first_id}–{last_id}.")
    n = last_id - first_id
    return _sysex(CMD_RQ1, [first_id >> 7, first_id & 0x7F, n >> 7, n & 0x7F])


def page_ids(page: int) -> tuple[int, int]:
    """Page (0-7 système, 8-807 patch k = page 8 + k) → (premier, dernier) ID de message."""
    first = page * PATCH_FRAMES
    return first, first + PATCH_FRAMES - 1


def patch_page(index: int) -> int:
    return PATCH_FIRST_COUNTER // PATCH_FRAMES + index


def _chunks(pages: list[int], size: int) -> list[list[int]]:
    """Regroupe des pages consécutives en blocs d'au plus `size` pages."""
    out: list[list[int]] = []
    for page in sorted(set(pages)):
        if out and page == out[-1][-1] + 1 and len(out[-1]) < size:
            out[-1].append(page)
        else:
            out.append([page])
    return out


def read_pages(
    out_port: str,
    in_port: str,
    pages: list[int],
    chunk_pages: int = DEFAULT_CHUNK_PAGES,
    idle_s: float = DEFAULT_IDLE_S,
    retries: int = DEFAULT_RETRIES,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[int, bytes], list[int]]:
    """Lit des pages ; rend (trames par ID de message, pages restées incomplètes)."""
    import mido

    wanted = {mid for page in pages for mid in range(page_ids(page)[0], page_ids(page)[1] + 1)}
    frames: dict[int, bytes] = {}

    def missing_pages() -> list[int]:
        return sorted({mid // PATCH_FRAMES for mid in wanted - frames.keys()})

    with mido.open_input(in_port) as inp, mido.open_output(out_port) as out:
        for _ in inp.iter_pending():
            pass

        def send(raw: bytes) -> None:
            out.send(mido.Message.from_bytes(raw))

        def collect(expected: set[int]) -> None:
            last = time.monotonic()
            while expected - frames.keys() and time.monotonic() - last < idle_s:
                msg = inp.poll()
                if msg is None:
                    time.sleep(0.002)
                    continue
                raw = bytes(msg.bytes())
                if len(raw) == 155 and is_es8_bulk_frame(raw):  # échos et autres messages ignorés
                    frame = parse_es8_bulk_frame(raw)  # ChecksumError : trame rejetée
                    if frame.counter in wanted:
                        is_new = frame.counter not in frames
                        frames[frame.counter] = raw
                        last = time.monotonic()
                        if is_new and on_progress is not None:
                            on_progress(len(frames), len(wanted))

        send(editor_mode_message(True))
        time.sleep(0.3)
        try:
            system = [p for p in pages if p * PATCH_FRAMES <= SYSTEM_LAST_ID]
            plan = ([sorted(set(system))] if system else []) + _chunks(
                [p for p in pages if p not in system], chunk_pages
            )
            for attempt in range(retries + 1):
                for block in plan:
                    first, last = page_ids(block[0])[0], page_ids(block[-1])[1]
                    if first <= SYSTEM_LAST_ID:
                        first, last = SYSTEM_REQUEST[0], max(last, SYSTEM_REQUEST[1])
                    send(request_message(first, last))
                    collect(set(range(first, last + 1)) & wanted)
                missing = missing_pages()  # nouvelle tentative : page par page (système d'un bloc)
                sys_missing = [p for p in missing if p * PATCH_FRAMES <= SYSTEM_LAST_ID]
                plan = ([sys_missing] if sys_missing else []) + [[p] for p in missing if p not in sys_missing]
                if not plan:
                    break
        finally:
            send(editor_mode_message(False))
    return frames, missing_pages()


def frames_to_syx(frames: dict[int, bytes]) -> bytes:
    return b"".join(frames[c] for c in sorted(frames))


__all__ = [
    "editor_mode_message",
    "frames_to_syx",
    "page_ids",
    "patch_page",
    "read_pages",
    "request_message",
]
