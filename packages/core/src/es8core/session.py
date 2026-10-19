"""Dialogue avec l'ES-8, indépendant du transport (mido en CLI, Web MIDI en navigateur).

Un transport n'a que deux opérations :
- `send(raw: bytes)` — envoyer un message MIDI complet ;
- `await receive(timeout_s) -> bytes | None` — le prochain message reçu, ou
  None après `timeout_s` sans rien.

Toute l'orchestration (lecture par blocs avec relances, rythme d'écriture)
est ici, en asynchrone, pour tourner telle quelle dans le CLI (asyncio) et
dans le navigateur (Pyodide, boucle d'événements du navigateur).
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Protocol

from .codec import PATCH_FRAMES, is_es8_bulk_frame, parse_es8_bulk_frame
from .codec.roland import CodecError
from .request import (
    DEFAULT_CHUNK_PAGES,
    DEFAULT_IDLE_S,
    DEFAULT_RETRIES,
    NAMELIST_FIRST_ID,
    NAMELIST_MESSAGES,
    NAMES_PER_MESSAGE,
    SYSTEM_LAST_ID,
    SYSTEM_REQUEST,
    _chunks,
    editor_mode_message,
    page_ids,
    parse_namelist_message,
    request_message,
)

FRAME_LEN = 155
MIN_INTERVAL_S = 0.05  # spec Roland


class Transport(Protocol):
    def send(self, raw: bytes) -> None: ...

    async def receive(self, timeout_s: float) -> bytes | None: ...


Sleep = Callable[[float], Awaitable[None]]


async def read_pages_async(
    transport: Transport,
    pages: list[int],
    chunk_pages: int = DEFAULT_CHUNK_PAGES,
    idle_s: float = DEFAULT_IDLE_S,
    retries: int = DEFAULT_RETRIES,
    on_progress: Callable[[int, int], None] | None = None,
    sleep: Sleep = asyncio.sleep,
) -> tuple[dict[int, bytes], list[int]]:
    """Lit des pages (RQ1) ; rend (trames par ID de message, pages restées incomplètes).

    Pages : 0-7 système, 8 + k patch k. Le système se demande 0..16 (voir
    request.py). Chaque page incomplète est redemandée seule ; les échos
    THRU et messages étrangers sont ignorés ; le mode éditeur est toujours
    désactivé en sortie.
    """
    wanted = {mid for page in pages for mid in range(page_ids(page)[0], page_ids(page)[1] + 1)}
    frames: dict[int, bytes] = {}

    def missing_pages() -> list[int]:
        return sorted({mid // PATCH_FRAMES for mid in wanted - frames.keys()})

    async def collect(expected: set[int]) -> None:
        while expected - frames.keys():
            raw = await transport.receive(idle_s)
            if raw is None:
                return  # silence : la suite viendra d'une relance
            if len(raw) != FRAME_LEN or not is_es8_bulk_frame(raw):
                continue
            try:
                frame = parse_es8_bulk_frame(raw)
            except CodecError:
                continue  # trame abîmée en route : sera redemandée
            if frame.counter in wanted:
                is_new = frame.counter not in frames
                frames[frame.counter] = raw
                if is_new and on_progress is not None:
                    on_progress(len(frames), len(wanted))

    transport.send(editor_mode_message(True))
    await sleep(0.3)
    try:
        system = sorted({p for p in pages if p * PATCH_FRAMES <= SYSTEM_LAST_ID})
        plan = ([system] if system else []) + _chunks([p for p in pages if p not in system], chunk_pages)
        for _ in range(retries + 1):
            for block in plan:
                first, last = page_ids(block[0])[0], page_ids(block[-1])[1]
                if first <= SYSTEM_LAST_ID:
                    first, last = SYSTEM_REQUEST[0], max(last, SYSTEM_REQUEST[1])
                transport.send(request_message(first, last))
                await collect(set(range(first, last + 1)) & wanted)
            missing = missing_pages()
            sys_missing = [p for p in missing if p * PATCH_FRAMES <= SYSTEM_LAST_ID]
            plan = ([sys_missing] if sys_missing else []) + [[p] for p in missing if p not in sys_missing]
            if not plan:
                break
    finally:
        transport.send(editor_mode_message(False))
    return frames, missing_pages()


async def read_names_async(
    transport: Transport,
    idle_s: float = DEFAULT_IDLE_S,
    retries: int = DEFAULT_RETRIES,
    on_progress: Callable[[int, int], None] | None = None,
    sleep: Sleep = asyncio.sleep,
) -> dict[int, str]:
    """Lit les 800 noms (liste des noms, 100 messages) ; les messages perdus sont redemandés."""
    names: dict[int, str] = {}
    total = NAMELIST_MESSAGES * NAMES_PER_MESSAGE

    async def collect(wanted: set[int]) -> None:
        while wanted - names.keys():
            raw = await transport.receive(idle_s)
            if raw is None:
                return
            got = parse_namelist_message(raw)
            if got:
                names.update(got)
                if on_progress is not None:
                    on_progress(len(names), total)

    transport.send(editor_mode_message(True))
    await sleep(0.3)
    try:
        missing = [(0, NAMELIST_MESSAGES - 1)]
        for _ in range(retries + 1):
            for first, last in missing:
                transport.send(request_message(NAMELIST_FIRST_ID + first, NAMELIST_FIRST_ID + last))
                await collect(set(range(first * NAMES_PER_MESSAGE, (last + 1) * NAMES_PER_MESSAGE)))
            gaps = sorted({n // NAMES_PER_MESSAGE for n in range(total)} - {n // NAMES_PER_MESSAGE for n in names})
            missing = [(m, m) for m in gaps]
            if not missing:
                break
    finally:
        transport.send(editor_mode_message(False))
    return names


async def send_frames_async(
    transport: Transport,
    frames: list[bytes],
    interval_s: float,
    page_gap_s: float,
    on_frame: Callable[[int, int], None] | None = None,
    sleep: Sleep = asyncio.sleep,
) -> int:
    """Envoie des pages : moitiés à `interval_s`, pause `page_gap_s` entre pages."""
    if interval_s < MIN_INTERVAL_S or page_gap_s < MIN_INTERVAL_S:
        raise ValueError(f"The Roland spec requires a delay of at least {MIN_INTERVAL_S} s.")
    if len(frames) % PATCH_FRAMES:
        raise ValueError("Odd number of frames: an incomplete page would be rejected.")
    sent = 0
    for frame in frames:
        if sent:
            await sleep(page_gap_s if sent % PATCH_FRAMES == 0 else interval_s)
        transport.send(frame)
        sent += 1
        if on_frame is not None:
            on_frame(sent, len(frames))
    return sent


class MidoTransport:
    """Transport CLI : ports mido déjà ouverts ; réception par scrutation."""

    def __init__(self, inp, out):
        self.inp, self.out = inp, out

    def send(self, raw: bytes) -> None:
        import mido

        self.out.send(mido.Message.from_bytes(raw))

    async def receive(self, timeout_s: float) -> bytes | None:
        deadline = time.monotonic() + timeout_s
        while True:
            msg = self.inp.poll() if self.inp is not None else None
            if msg is not None:
                return bytes(msg.bytes())
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.002)


async def write_confirmed_async(
    transport: Transport,
    frames: list[bytes],
    interval_s: float,
    page_gap_s: float,
    rounds: int = 3,
    on_progress: Callable[[str, int, int], None] | None = None,
    sleep: Sleep = asyncio.sleep,
    already_sent: bool = False,
) -> dict:
    """Écrit des pages puis les relit (RQ1) et renvoie les non conformes, jusqu'à `rounds` tours.

    `on_progress(phase, n, total)` : phase « send », « read » ou « resend ».
    `already_sent` : l'envoi initial a déjà eu lieu (CLI) ; ne faire que vérifier.
    Rend {"confirmed", "history", "pending_counters"} — `pending_counters` :
    premier ID de message de chaque page restée non conforme.
    """
    from .apply import pending_pages

    def report(phase):
        return (lambda n, t: on_progress(phase, n, t)) if on_progress else None

    if not already_sent:
        await send_frames_async(transport, frames, interval_s, page_gap_s, report("send"), sleep)
    todo = [frames[i : i + PATCH_FRAMES] for i in range(0, len(frames), PATCH_FRAMES)]
    history = []
    for round_no in range(1, rounds + 2):
        pages = sorted({parse_es8_bulk_frame(p[0]).counter // PATCH_FRAMES for p in todo})
        device, _ = await read_pages_async(transport, pages, on_progress=report("read"), sleep=sleep)
        todo = pending_pages([f for p in todo for f in p], device)
        history.append({"round": round_no, "checked": len(pages), "pending": len(todo)})
        if not todo or round_no > rounds:
            break
        await send_frames_async(
            transport, [f for p in todo for f in p], interval_s, page_gap_s, report("resend"), sleep
        )
    return {
        "confirmed": not todo,
        "history": history,
        "pending_counters": [parse_es8_bulk_frame(p[0]).counter for p in todo],
    }
