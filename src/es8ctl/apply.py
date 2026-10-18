"""Préparation d'une écriture vers l'ES-8 : changements JSON → pages → trames.

Tout est validé avant que la moindre trame ne soit construite : patch
inconnu ou incomplet dans le dump de base, champ inconnu, valeur hors
bornes. Seules les pages réellement modifiées sont émises ; chacune est
ré-encodée depuis la page de base, donc les bits non modifiés (y compris
non cartographiés) sont repris à l'identique.

Format des changements (forme des valeurs = celle de `es8ctl patches` /
`es8ctl system`) :

    {
      "patches": {"0-1": {"master_bpm": 107, "name": "MY PATCH        "}},
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
from .system import SYSTEM_PAGES, decode_system, encode_system

# Spec Roland : au moins 50 ms entre deux messages. Marge de sécurité.
DEFAULT_INTERVAL_S = 0.06


@dataclass(frozen=True)
class Plan:
    """Écriture préparée : trames à envoyer, dans l'ordre, et différences lisibles."""

    frames: list[bytes]
    changes: list[dict]
    expected: bytes  # dump complet attendu après écriture (.syx)

    def duration_s(self, interval_s: float = DEFAULT_INTERVAL_S) -> float:
        return len(self.frames) * interval_s


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


def plan_changes(base_frames: list[bytes], changes: dict) -> Plan:
    """Construit le plan d'écriture. Lève CodecError au moindre problème."""
    if not isinstance(changes, dict) or set(changes) - {"patches", "system"}:
        raise CodecError('Changements : objet JSON avec les clés "patches" et/ou "system".')
    dump = split_dump(base_frames)
    data = frames_by_counter(base_frames)
    frames: list[bytes] = []
    diffs: list[dict] = []
    new_data = dict(data)

    system_changes = changes.get("system") or {}
    if system_changes:
        if dump.system is None:
            raise CodecError("Le dump de base n'a pas de bloc système : impossible de le modifier.")
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
        raise CodecError('"patches" : objet {"banque-numéro": {champ: valeur}} attendu.')
    for label in sorted(patch_changes, key=parse_patch_label):
        index = parse_patch_label(label)
        if index not in dump.patches:
            raise CodecError(f"Patch {label} absent ou incomplet dans le dump de base.")
        record = dump.patches[index]
        page = unpack_page(record)
        edited = encode_patch(page, patch_changes[label])
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
