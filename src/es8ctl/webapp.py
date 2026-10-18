"""Pont entre l'interface web (navigateur, Pyodide) et la bibliothèque es8ctl.

Le JavaScript ne fait que deux choses : brancher Web MIDI et afficher. Toute
la logique (lecture RQ1 avec relances, décodage, routing) est celle du CLI.

- `set_sender(fn)` : fonction JS qui envoie une liste d'octets sur la sortie MIDI ;
- `push(data)` : à appeler pour chaque message MIDI reçu (Uint8Array) ;
- `await read_device(on_progress)` : lit tout l'appareil ;
- `load_syx(data)` : charge un .syx (mode hors ligne) ;
- `bank_grid()`, `patch_detail(label)`, `system_summary()` : JSON pour l'affichage.
"""

from __future__ import annotations

import asyncio
import json

from .codec import (
    PATCH_COUNT,
    patch_label,
    split_dump,
    split_frames,
    unpack_page,
)
from .names import ASSIGN_TARGETS, CTL_FUNCTIONS, CTL_SLOTS, LOOPS
from .patch import decode_patch, out_of_range
from .request import DEFAULT_IDLE_S, patch_page
from .routing import render
from .session import read_pages_async
from .system import decode_system

ASSIGN_SOURCES = (
    "CTL1", "CTL2", "CTL3", "CTL4", "MemM", "Mute", "BnkD", "BnkU",
    "Num1", "Num2", "Num3", "Num4", "Num5", "Num6", "Num7", "Num8",
    "CNum", "EXP1", "EXP2", "INT", "WAV", "CC",
)


class WebMidiTransport:
    """Transport alimenté par le navigateur : `push` à chaque message reçu."""

    def __init__(self) -> None:
        self.sender = None
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()

    def send(self, raw: bytes) -> None:
        if self.sender is None:
            raise RuntimeError("Aucune sortie MIDI sélectionnée.")
        self.sender(list(raw))

    async def receive(self, timeout_s: float) -> bytes | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout_s)
        except asyncio.TimeoutError:
            return None


transport = WebMidiTransport()
state: dict = {"frames": {}, "dump": None, "source": None}


def set_sender(fn) -> None:
    transport.sender = fn


def push(data) -> None:
    raw = bytes(data.to_py()) if hasattr(data, "to_py") else bytes(data)
    if raw[:1] == b"\xf0":  # SysEx uniquement (le reste ne sert pas à l'éditeur)
        transport.queue.put_nowait(raw)


def _set_frames(frames: dict[int, bytes], source: str) -> None:
    state["frames"] = frames
    state["dump"] = split_dump(list(frames.values()))
    state["source"] = source


async def read_device(on_progress=None, idle_s: float = DEFAULT_IDLE_S) -> str:
    """Lit système + 800 patchs ; rend un résumé JSON."""
    while not transport.queue.empty():
        transport.queue.get_nowait()
    pages = list(range(8)) + [patch_page(i) for i in range(PATCH_COUNT)]
    frames, missing = await read_pages_async(
        transport, pages, idle_s=idle_s,
        on_progress=(lambda n, t: on_progress(n, t)) if on_progress else None,
    )
    _set_frames(frames, "device")
    return json.dumps({"frames": len(frames), "missing_pages": missing})


def load_syx(data) -> str:
    raw = bytes(data.to_py()) if hasattr(data, "to_py") else bytes(data)
    from .codec import parse_es8_bulk_frame

    frames = {parse_es8_bulk_frame(f).counter: f for f in split_frames(raw)}
    _set_frames(frames, "file")
    return json.dumps({"frames": len(frames), "patches": len(state["dump"].patches)})


def syx_bytes():
    """Dump courant au format .syx (pour téléchargement)."""
    from .request import frames_to_syx

    return frames_to_syx(state["frames"])


def _decoded(index: int) -> dict | None:
    record = state["dump"].patches.get(index) if state["dump"] else None
    return decode_patch(unpack_page(record)) if record is not None else None


def bank_grid() -> str:
    """800 cellules : nom, chaîne, BPM, loops actives."""
    cells = []
    for index in range(PATCH_COUNT):
        fields = _decoded(index)
        if fields is None:
            cells.append({"patch": patch_label(index), "missing": True})
            continue
        cells.append({
            "patch": patch_label(index),
            "name": fields["name"].rstrip(),
            "chain": render(fields["loop_position"]),
            "bpm": fields["master_bpm"],
            "loops": [LOOPS[i] for i, on in enumerate(fields["loop_sw"]) if on],
        })
    current = None
    if state["dump"] and state["dump"].system is not None:
        current = patch_label(decode_system(state["dump"].system)["current_num"])
    return json.dumps({"source": state["source"], "current": current, "cells": cells})


def patch_detail(label: str) -> str:
    from .codec import parse_patch_label

    fields = _decoded(parse_patch_label(label))
    if fields is None:
        return json.dumps({"patch": label, "missing": True})
    ctl = [
        {"slot": CTL_SLOTS[i], "function": CTL_FUNCTIONS[v] if v < len(CTL_FUNCTIONS) else v}
        for i, v in enumerate(fields["ctl_func"])
    ]
    assigns = [
        {
            "n": i + 1,
            "source": ASSIGN_SOURCES[fields["assign_source"][i]]
            if fields["assign_source"][i] < len(ASSIGN_SOURCES) else fields["assign_source"][i],
            "target": ASSIGN_TARGETS[fields["assign_target"][i]]
            if fields["assign_target"][i] < len(ASSIGN_TARGETS) else fields["assign_target"][i],
            "mode": "TGL" if fields["assign_mode"][i] else "MOM",
            "range": [fields["assign_target_min"][i], fields["assign_target_max"][i]],
            "cc": [fields["assign_target_cc_ch"][i] + 1, fields["assign_target_cc_no"][i]],
        }
        for i in range(12)
        if fields["assign_sw"][i]
    ]
    midi = [
        {"ch": fields["midi_tx_ch"][i], "pc": fields["midi_pc"][i],
         "bank": [fields["midi_pc_bank_msb"][i], fields["midi_pc_bank_lsb"][i]]}
        for i in range(8)
        if fields["midi_tx_ch"][i]
    ]
    return json.dumps({
        "patch": label,
        "name": fields["name"],
        "chain": render(fields["loop_position"]),
        "bpm": fields["master_bpm"],
        "loops": {LOOPS[i]: bool(v) for i, v in enumerate(fields["loop_sw"])},
        "carry_over": [LOOPS[i] for i, v in enumerate(fields["carry_over_loop"]) if v],
        "ctl": ctl,
        "assigns": assigns,
        "midi": midi,
        "warnings": out_of_range(fields),
        "fields": fields,
    })


def system_summary() -> str:
    if not state["dump"] or state["dump"].system is None:
        return json.dumps(None)
    return json.dumps(decode_system(state["dump"].system))
