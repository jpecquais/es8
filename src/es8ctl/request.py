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

from typing import Callable

from .codec import BULK_LAST_COUNTER, PATCH_FIRST_COUNTER, PATCH_FRAMES
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
    """Lit des pages par ports mido ; rend (trames par ID, pages incomplètes).

    Enveloppe synchrone de `session.read_pages_async` (même logique que le navigateur).
    """
    import asyncio

    import mido

    from .session import MidoTransport, read_pages_async

    with mido.open_input(in_port) as inp, mido.open_output(out_port) as out:
        for _ in inp.iter_pending():
            pass
        return asyncio.run(
            read_pages_async(
                MidoTransport(inp, out), pages, chunk_pages=chunk_pages, idle_s=idle_s,
                retries=retries, on_progress=on_progress,
            )
        )


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
