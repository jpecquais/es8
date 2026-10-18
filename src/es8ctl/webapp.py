"""Pont entre l'interface web (navigateur, Pyodide) et la bibliothèque es8ctl.

Le JavaScript ne fait que deux choses : brancher Web MIDI et afficher. Toute
la logique (lecture RQ1 avec relances, décodage, routing) est celle du CLI.

- `set_sender(fn)` : fonction JS qui envoie une liste d'octets sur la sortie MIDI ;
- `push(data)` : à appeler pour chaque message MIDI reçu (Uint8Array) ;
- `await read_device(on_progress)` : lit tout l'appareil ;
- `load_syx(data)` : charge un .syx (mode hors ligne) ;
- `bank_grid()`, `patch_detail(label)`, `system_summary()` : JSON pour l'affichage
  (état de l'appareil avec les modifications en attente appliquées) ;
- `stage(label, json)`, `stage_system(json)`, `transform_set(...)`,
  `transform_swap(...)`, `discard(label)` : modifications en attente, validées
  à chaque ajout ;
- `await write_pending(on_progress)` : écriture vérifiée (relecture + renvoi).
"""

from __future__ import annotations

import asyncio
import copy
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
pending: dict = {"patches": {}, "system": {}}
_preview_cache: dict = {}


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
    _preview_cache.clear()


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


def _changes() -> dict:
    out = {"patches": pending["patches"]}
    if pending["system"]:
        out["system"] = pending["system"]
    return out


def _plan(changes: dict | None = None):
    from .apply import plan_changes

    return plan_changes(list(state["frames"].values()), changes or _changes())


def _preview():
    """Dump affiché : l'appareil, modifications en attente appliquées."""
    if not (pending["patches"] or pending["system"]):
        return state["dump"]
    if "dump" not in _preview_cache:
        _preview_cache["dump"] = split_dump(list(split_frames(_plan().expected)))
    return _preview_cache["dump"]


def _decoded(index: int) -> dict | None:
    dump = _preview()
    record = dump.patches.get(index) if dump else None
    return decode_patch(unpack_page(record)) if record is not None else None


def _merge(target: dict, changes: dict) -> dict:
    """Fusionne des changements dans une copie des modifications en attente."""
    merged = copy.deepcopy(target)
    for label, fields in (changes.get("patches") or {}).items():
        current = merged["patches"].setdefault(label, {})
        if "loop_chain" in fields:
            current.pop("loop_position", None)
        if "loop_position" in fields:
            current.pop("loop_chain", None)
        current.update(fields)
    merged["system"].update(changes.get("system") or {})
    return merged


def _accept(changes: dict) -> str:
    """Valide (plan complet) puis adopte ; erreur JSON sinon, rien n'est changé."""
    global pending
    from .codec import CodecError

    trial = _merge(pending, changes)
    try:
        candidate = {"patches": trial["patches"], **({"system": trial["system"]} if trial["system"] else {})}
        _plan(candidate)
    except (CodecError, ValueError) as exc:
        return json.dumps({"error": str(exc)})
    pending = trial
    _preview_cache.clear()
    return pending_summary()


def stage(label: str, fields_json: str) -> str:
    return _accept({"patches": {label: json.loads(fields_json)}})


def stage_system(fields_json: str) -> str:
    return _accept({"system": json.loads(fields_json)})


def stage_changes(changes_json: str) -> str:
    """Changements au format de `es8ctl apply` (ex. issus d'un fichier ou d'un import .bel)."""
    return _accept(json.loads(changes_json))


def transform_set(assignments_json: str, selection: str = "all") -> str:
    from .codec import CodecError
    from .transform import op_set, select_patches

    try:
        dump = _preview()
        changes = op_set(dump, select_patches(dump, selection or "all"), json.loads(assignments_json))
    except (CodecError, ValueError) as exc:
        return json.dumps({"error": str(exc)})
    return _accept(changes)


def transform_swap(loop_a: str, loop_b: str, selection: str = "all") -> str:
    from .codec import CodecError
    from .transform import op_swap_loops, select_patches

    try:
        dump = _preview()
        changes = op_swap_loops(dump, select_patches(dump, selection or "all"), loop_a, loop_b)
    except (CodecError, ValueError) as exc:
        return json.dumps({"error": str(exc)})
    return _accept(changes)


def discard(label: str | None = None) -> str:
    global pending
    if label is None:
        pending = {"patches": {}, "system": {}}
    elif label == "system":
        pending["system"] = {}
    else:
        pending["patches"].pop(label, None)
    _preview_cache.clear()
    return pending_summary()


def pending_summary() -> str:
    from .apply import DEFAULT_INTERVAL_S, DEFAULT_PAGE_GAP_S

    if not (pending["patches"] or pending["system"]) or not state["frames"]:
        return json.dumps({"changes": [], "frames": 0, "estimated_s": 0, "patches": []})
    plan = _plan()
    return json.dumps({
        "changes": plan.changes,
        "frames": len(plan.frames),
        "estimated_s": round(plan.duration_s(DEFAULT_INTERVAL_S, DEFAULT_PAGE_GAP_S)),
        "patches": sorted({c["target"] for c in plan.changes if c["target"] != "system"}),
        "system": bool(pending["system"]),
    })


async def write_pending(on_progress=None) -> str:
    """Écrit les modifications en attente, relit et renvoie jusqu'à confirmation."""
    global pending
    from .apply import DEFAULT_INTERVAL_S, DEFAULT_PAGE_GAP_S
    from .codec import parse_es8_bulk_frame
    from .session import write_confirmed_async

    plan = _plan()
    if not plan.frames:
        return json.dumps({"confirmed": True, "history": [], "not_confirmed": [], "frames": 0})
    while not transport.queue.empty():
        transport.queue.get_nowait()
    result = await write_confirmed_async(
        transport, plan.frames, DEFAULT_INTERVAL_S, DEFAULT_PAGE_GAP_S,
        on_progress=(lambda phase, n, t: on_progress(phase, n, t)) if on_progress else None,
    )
    failed = set(result["pending_counters"])
    failed_pages = {c // 2 for c in failed}
    # L'état local adopte les pages confirmées ; les autres restent en attente.
    expected = {parse_es8_bulk_frame(f).counter: f for f in split_frames(plan.expected)}
    frames = dict(state["frames"])
    for counter, frame in expected.items():
        if counter // 2 not in failed_pages:
            frames[counter] = frame
    not_confirmed = sorted(patch_label(p - 8) if p >= 8 else "system" for p in failed_pages)
    kept = {"patches": {k: v for k, v in pending["patches"].items() if k in not_confirmed},
            "system": pending["system"] if "system" in not_confirmed else {}}
    _set_frames(frames, state["source"] or "device")
    pending = kept
    return json.dumps({"confirmed": result["confirmed"], "history": result["history"],
                       "not_confirmed": not_confirmed, "frames": len(plan.frames)})


def names() -> str:
    from .names import ASSIGN_TARGETS as TARGETS

    return json.dumps({
        "loops": LOOPS, "ctl_slots": CTL_SLOTS, "ctl_functions": CTL_FUNCTIONS,
        "assign_sources": ASSIGN_SOURCES, "assign_targets": TARGETS,
    })


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
            "pending": patch_label(index) in pending["patches"],
            "name": fields["name"].rstrip(),
            "chain": render(fields["loop_position"]),
            "bpm": fields["master_bpm"],
            "loops": [LOOPS[i] for i, on in enumerate(fields["loop_sw"]) if on],
        })
    current = None
    if state["dump"] and state["dump"].system is not None:
        current = patch_label(decode_system(state["dump"].system)["current_num"])
    return json.dumps({"source": state["source"], "current": current, "cells": cells,
                       "pending_count": len(pending["patches"]) + bool(pending["system"])})


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
        "pending": pending["patches"].get(label, {}),
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
    dump = _preview()
    if not dump or dump.system is None:
        return json.dumps(None)
    return json.dumps(decode_system(dump.system))
