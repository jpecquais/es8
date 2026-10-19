"""Préparation d'une écriture vers l'ES-8 : changements JSON → pages → trames.

Tout est validé avant que la moindre trame ne soit construite : patch
inconnu ou incomplet dans le dump de base, champ inconnu, valeur hors
bornes. Seules les pages réellement modifiées sont émises ; chacune est
ré-encodée depuis la page de base, donc les bits non modifiés (y compris
non cartographiés) sont repris à l'identique.

Format des changements (forme des valeurs = celle de `es8ctl patches` /
`es8ctl system`) :

    {
      "patches": {"0-1": {"master_bpm": 107, "name": "MY PATCH        ",
                          "loop_chain": "V8746(3//5)21"}},
      "system": {"others_lcd_contrast": 5}
    }

Aucun accès MIDI ici : l'envoi est dans `transfer.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codec import (
    PATCH_FIRST_COUNTER,
    PATCH_FRAMES,
    SYSTEM_FIRST_COUNTER,
    BULK_DATA_LEN,
    CodecError,
    build_es8_bulk_frame,
    frames_by_counter,
    pack_page,
    parse_patch_label,
    patch_label,
    split_dump,
    unpack_page,
)
from .patch import decode_patch, encode_patch
from .routing import parse as parse_chain
from .routing import problems as routing_problems
from .system import SYSTEM_PAGES, decode_system, encode_system

# Spec Roland : au moins 50 ms entre deux messages. Marge de sécurité.
DEFAULT_INTERVAL_S = 0.06
# Pause entre deux pages (voir transfer.py). Via une interface Bluetooth : 0,5 s → ~1,7 % de pages
# perdues au 1er passage (800 pages) ; 0,25 s → 0 / 40 ; 0,1 s → 4 / 40.
DEFAULT_PAGE_GAP_S = 0.25

# Condition côté appareil, établie le 2026-10-18 : sur l'écran Utility > Bulk
# Dump (où il reste après un dump déclenché au panneau), l'ES-8 ignore
# silencieusement tout bulk dump reçu.
DEVICE_PRECONDITION = (
    "The ES-8 must be on its play screen: after a dump from the panel, leave "
    "the Bulk Dump screen (EXIT), otherwise it silently ignores the pages it receives."
)


@dataclass(frozen=True)
class Plan:
    """Écriture préparée : trames à envoyer, dans l'ordre, et différences lisibles."""

    frames: list[bytes]
    changes: list[dict]
    expected: bytes  # dump complet attendu après écriture (.syx)

    def duration_s(
        self, interval_s: float = DEFAULT_INTERVAL_S, page_gap_s: float = DEFAULT_PAGE_GAP_S
    ) -> float:
        pages = len(self.frames) // PATCH_FRAMES
        return pages * interval_s + max(pages - 1, 0) * page_gap_s


def _page_frames(first_counter: int, record: bytes) -> list[bytes]:
    return [
        build_es8_bulk_frame(first_counter + i, record[i * BULK_DATA_LEN : (i + 1) * BULK_DATA_LEN])
        for i in range(PATCH_FRAMES)
    ]


def _field_changes(target: str, before: dict, after: dict) -> list[dict]:
    return [
        {"target": target, "field": name, "old": before[name], "new": after[name]}
        for name in after
        if after[name] != before[name]
    ]


def _with_positions(page: bytes, fields: dict) -> dict:
    """Traduit `loop_chain` (notation de l'écran) en `loop_position`."""
    if not isinstance(fields, dict):
        raise CodecError("Patch changes: expected an object {field: value}.")
    if "loop_chain" not in fields:
        return fields
    if "loop_position" in fields:
        raise CodecError("Give loop_chain or loop_position, not both.")
    fields = dict(fields)
    text = fields.pop("loop_chain")
    if not isinstance(text, str):
        raise CodecError("loop_chain: expected a string (e.g. \"V8746(3//5)21\").")
    fields["loop_position"] = parse_chain(text, base=decode_patch(page)["loop_position"])
    return fields


def _check_routing(label: str, before: dict, after: dict, stereo: tuple[bool, bool]) -> None:
    """Refuse une chaîne que l'ES-8 ne sait pas faire, si la modification la crée."""
    new = set(routing_problems(after["loop_position"], after["carry_over_loop"], *stereo)) - set(
        routing_problems(before["loop_position"], before["carry_over_loop"], *stereo)
    )
    if new:
        raise CodecError(f"{label}: {' '.join(sorted(new))}")


def plan_changes(base_frames: list[bytes], changes: dict) -> Plan:
    """Construit le plan d'écriture. Lève CodecError au moindre problème."""
    if not isinstance(changes, dict) or set(changes) - {"patches", "system"}:
        raise CodecError('Changes: expected a JSON object with "patches" and/or "system".')
    dump = split_dump(base_frames)
    data = frames_by_counter(base_frames)
    frames: list[bytes] = []
    diffs: list[dict] = []
    new_data = dict(data)

    system_changes = changes.get("system") or {}
    if system_changes:
        if dump.system is None:
            raise CodecError("The base dump has no system block: cannot change it.")
        before = decode_system(dump.system)
        edited = encode_system(dump.system, system_changes)
        diffs += _field_changes("system", before, decode_system(edited))
        for page in range(SYSTEM_PAGES):
            start = page * PATCH_FRAMES * BULK_DATA_LEN
            old = dump.system[start : start + PATCH_FRAMES * BULK_DATA_LEN]
            new = edited[start : start + PATCH_FRAMES * BULK_DATA_LEN]
            if new != old:
                first = SYSTEM_FIRST_COUNTER + page * PATCH_FRAMES
                frames += _page_frames(first, new)

    patch_changes = changes.get("patches") or {}
    if not isinstance(patch_changes, dict):
        raise CodecError('"patches": expected an object {"bank-number": {field: value}}.')
    stereo = (False, False)
    if dump.system is not None:
        sys_now = decode_system(encode_system(dump.system, system_changes) if system_changes else dump.system)
        stereo = (bool(sys_now["preference_loop7_return_mode"]), bool(sys_now["preference_loop8_return_mode"]))
    for label in sorted(patch_changes, key=parse_patch_label):
        index = parse_patch_label(label)
        if index not in dump.patches:
            raise CodecError(f"Patch {label} is missing or incomplete in the base dump.")
        record = dump.patches[index]
        page = unpack_page(record)
        edited = encode_patch(page, _with_positions(page, patch_changes[label]))
        _check_routing(label, decode_patch(page), decode_patch(edited), stereo)
        diffs += _field_changes(patch_label(index), decode_patch(page), decode_patch(edited))
        if edited != page:
            frames += _page_frames(PATCH_FIRST_COUNTER + index * PATCH_FRAMES, pack_page(edited))

    for frame in frames:
        counter = frame[8] * 128 + frame[9]
        new_data[counter] = frame[10:-2]
    expected = b"".join(
        build_es8_bulk_frame(counter, new_data[counter]) for counter in sorted(new_data)
    )
    return Plan(frames=frames, changes=diffs, expected=expected)


def check_changes(actual_frames: list[bytes], changes: dict) -> dict:
    """Vérifie, patch par patch, que les valeurs demandées sont dans un dump.

    Complète `verify` : utile quand plusieurs écritures partent d'une même
    base, ou pour savoir précisément quelles pages d'un envoi sont arrivées.
    """
    if not isinstance(changes, dict) or set(changes) - {"patches", "system"}:
        raise CodecError('Changes: expected a JSON object with "patches" and/or "system".')
    dump = split_dump(actual_frames)
    results: list[dict] = []

    def compare(target: str, actual: dict, wanted: dict) -> None:
        mismatches = [
            {"field": k, "wanted": v, "actual": actual[k]} for k, v in wanted.items() if actual[k] != v
        ]
        results.append({"target": target, "applied": not mismatches, "mismatches": mismatches})

    for label in sorted(changes.get("patches") or {}, key=parse_patch_label):
        index = parse_patch_label(label)
        if index not in dump.patches:
            results.append({"target": label, "applied": None, "error": "absent ou incomplet du dump"})
            continue
        page = unpack_page(dump.patches[index])
        wanted = _with_positions(page, changes["patches"][label])
        unknown = set(wanted) - set(decode_patch(page))
        if unknown:
            raise CodecError(f"Unknown fields: {', '.join(sorted(unknown))}.")
        compare(label, decode_patch(page), wanted)
    if changes.get("system"):
        if dump.system is None:
            results.append({"target": "system", "applied": None, "error": "no system block"})
        else:
            compare("system", decode_system(dump.system), changes["system"])
    applied = [r["target"] for r in results if r["applied"]]
    return {
        "applied_count": len(applied),
        "total": len(results),
        "not_applied": [r["target"] for r in results if r["applied"] is False],
        "results": results,
    }


def pending_pages(plan_frames: list[bytes], device: dict[int, bytes]) -> list[list[bytes]]:
    """Pages du plan absentes ou différentes dans une relecture de l'appareil.

    Rend les trames à renvoyer, groupées par page. Pour le bloc système, le
    patch sélectionné (`current_num`, change à chaque navigation) est ignoré :
    le renvoyer ramènerait l'ES-8 sur l'ancien patch.
    """
    from .codec import parse_es8_bulk_frame

    pages = [plan_frames[i : i + PATCH_FRAMES] for i in range(0, len(plan_frames), PATCH_FRAMES)]
    pending = []
    for page in pages:
        counters = [parse_es8_bulk_frame(f).counter for f in page]
        got = [device.get(c) for c in counters]
        if got == page:
            continue
        if None not in got and counters[0] < PATCH_FIRST_COUNTER:
            wanted = decode_system_page(counters[0] // PATCH_FRAMES, b"".join(f[10:-2] for f in page))
            actual = decode_system_page(counters[0] // PATCH_FRAMES, b"".join(f[10:-2] for f in got))
            if {k: v for k, v in wanted.items() if k != "current_num"} == {
                k: v for k, v in actual.items() if k != "current_num"
            }:
                continue
        pending.append(page)
    return pending


def decode_system_page(page: int, record: bytes) -> dict:
    from .layout import decode_fields
    from .system import PAGE_FIELDS

    return decode_fields(unpack_page(record), PAGE_FIELDS[page])
