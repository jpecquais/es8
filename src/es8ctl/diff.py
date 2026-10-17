"""Comparaison de deux bulk dumps ES-8 : bloc système et patchs.

Outil central du reverse-engineering différentiel : le dump étant
déterministe, changer un seul paramètre au panneau puis re-dumper fait
apparaître exactement les bits qui l'encodent.

Les patchs sont comparés dans le domaine dépaquetés (250 octets 8 bits,
flux de bits MSB d'abord) : les positions rapportées sont directement
celles de la future carte des champs. Le bloc système, dont l'encodage
n'est pas encore établi, est comparé octet par octet dans le domaine MIDI.

Read-only, hors ligne : ne touche jamais au MIDI.
"""

from __future__ import annotations

from pathlib import Path

from .codec import (
    BulkDump,
    get_bits,
    patch_label,
    patch_name,
    split_dump,
    split_frames,
    unpack_page,
)


def _bit_runs(a: bytes, b: bytes) -> list[dict]:
    """Plages contiguës de bits modifiés, avec valeurs avant/après."""
    changed = [
        pos for pos in range(len(a) * 8) if get_bits(a, pos, 1) != get_bits(b, pos, 1)
    ]
    runs: list[list[int]] = []
    for pos in changed:
        if runs and pos == runs[-1][1] + 1:
            runs[-1][1] = pos
        else:
            runs.append([pos, pos])
    return [
        {
            "bit": start,
            "width": end - start + 1,
            "old": get_bits(a, start, end - start + 1),
            "new": get_bits(b, start, end - start + 1),
        }
        for start, end in runs
    ]


def _label_ranges(indices: list[int]) -> list[str]:
    """Plages de patchs lisibles : [0, 1, 2, 5] → ["1-1..1-3", "1-6"]."""
    ranges: list[list[int]] = []
    for index in sorted(indices):
        if ranges and index == ranges[-1][1] + 1:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])
    return [
        patch_label(lo) if lo == hi else f"{patch_label(lo)}..{patch_label(hi)}"
        for lo, hi in ranges
    ]


def _system_diff(a: bytes | None, b: bytes | None) -> dict:
    if a is None or b is None:
        return {"compared": False, "present": {"a": a is not None, "b": b is not None}}
    changes = [
        {"offset": pos, "old": f"{x:02x}", "new": f"{y:02x}"}
        for pos, (x, y) in enumerate(zip(a, b))
        if x != y
    ]
    return {"compared": True, "changes": changes}


def diff_dumps(a: BulkDump, b: BulkDump) -> dict:
    """Compare deux dumps découpés ; ne compare que ce qui est présent des deux côtés."""
    patches = []
    for index in sorted(a.patches.keys() & b.patches.keys()):
        if a.patches[index] == b.patches[index]:
            continue
        old, new = unpack_page(a.patches[index]), unpack_page(b.patches[index])
        entry = {
            "patch_index": index,
            "patch": patch_label(index),
            "name": {"old": patch_name(old), "new": patch_name(new)},
            "bit_runs": _bit_runs(old, new),
        }
        patches.append(entry)

    system = _system_diff(a.system, b.system)
    return {
        "changed": bool(patches or system.get("changes")),
        "system": system,
        "changed_patch_count": len(patches),
        "patches": patches,
        "coverage": {
            "only_in_a": _label_ranges(list(a.patches.keys() - b.patches.keys())),
            "only_in_b": _label_ranges(list(b.patches.keys() - a.patches.keys())),
            "incomplete": {
                "a": _label_ranges(a.incomplete),
                "b": _label_ranges(b.incomplete),
            },
        },
    }


def load_dump(path: Path) -> BulkDump:
    return split_dump(list(split_frames(Path(path).read_bytes())))


def diff_files(a: Path, b: Path) -> dict:
    """Compare deux fichiers .syx de bulk dump ES-8."""
    return {"a": str(a), "b": str(b), **diff_dumps(load_dump(a), load_dump(b))}
