"""Import / export au format `.bel` de l'éditeur officiel BOSS (ES-8 v2).

Un `.bel` est un JSON : {"target": "ES-8", "format": 100, "system": {...},
"patch": [800 objets]}. Les clés sont les `ID_PATCH_*` / `ID_SYSTEM_*` de
l'éditeur ; nos noms de champs en sont la version minuscule sans préfixe,
dans le même ordre (seule exception : `ID_PATCH_LOOP_SW_LOOP` ↔ `loop_sw`).
Le nom d'un patch y est une liste de 16 codes ASCII.

Limite, signalée dans `warnings` :
- sur les anciennes captures, le dernier message d'un dump (patch 99-8, seconde moitié) n'est jamais
  reçu : à l'export, 99-8 est reconstitué à partir du patch d'usine si sa
  première moitié lui est identique, sinon complété par la seconde moitié
  d'usine (avertissement).
"""

from __future__ import annotations

from collections import Counter

from .codec import BULK_DATA_LEN, PATCH_COUNT, BulkDump, CodecError, patch_label, unpack_page
from .patch import PATCH_FIELDS, decode_patch
from .system import SYSTEM_FIELDS, decode_system

BEL_TARGET = "ES-8"
BEL_FORMAT = 100

_PATCH_KEY_OVERRIDES = {"loop_sw": "ID_PATCH_LOOP_SW_LOOP"}


def patch_key(name: str) -> str:
    return _PATCH_KEY_OVERRIDES.get(name, f"ID_PATCH_{name.upper()}")


def system_key(name: str) -> str:
    return f"ID_SYSTEM_{name.upper()}"


def _to_bel(name: str, value):
    return [ord(c) for c in value] if name == "name" else value


def _from_bel(name: str, value):
    if name == "name":
        if not isinstance(value, list) or not all(isinstance(c, int) for c in value):
            raise CodecError("ID_PATCH_NAME : liste de codes ASCII attendue.")
        return "".join(map(chr, value))
    return value


def _factory_record(dump: BulkDump) -> bytes:
    return Counter(dump.patches.values()).most_common(1)[0][0]


def export_bel(dump: BulkDump, last_frames: dict[int, bytes] | None = None) -> tuple[dict, list[str]]:
    """Dump → document `.bel`. Rend (document, avertissements).

    `last_frames` : données des trames du dump par compteur, pour
    reconstituer un patch incomplet (99-8).
    """
    if dump.system is None:
        raise CodecError("Le dump n'a pas de bloc système : export .bel impossible.")
    warnings: list[str] = []
    factory = _factory_record(dump)
    patches = []
    for index in range(PATCH_COUNT):
        record = dump.patches.get(index)
        if record is None:
            first = (last_frames or {}).get(16 + 2 * index)
            if first is None:
                raise CodecError(f"Patch {patch_label(index)} absent du dump : export .bel impossible.")
            record = first + factory[BULK_DATA_LEN:]
            same = first == factory[:BULK_DATA_LEN]
            warnings.append(
                f"{patch_label(index)} : seconde moitié jamais reçue, reprise du patch d'usine"
                + (" (première moitié identique à l'usine)." if same else " — à vérifier.")
            )
        fields = decode_patch(unpack_page(record))
        patches.append({patch_key(f.name): _to_bel(f.name, fields[f.name]) for f in PATCH_FIELDS})

    system_fields = decode_system(dump.system)
    system = {system_key(f.name): system_fields[f.name] for f in SYSTEM_FIELDS}
    return {"target": BEL_TARGET, "format": BEL_FORMAT, "system": system, "patch": patches}, warnings


def import_bel(document: dict, base: BulkDump) -> tuple[dict, list[str]]:
    """Document `.bel` → changements JSON (pour `apply`) par rapport au dump `base`.

    Seuls les champs qui diffèrent de `base` sont retenus. Clé inconnue ou
    manquante = erreur.
    """
    if not isinstance(document, dict) or document.get("target") != BEL_TARGET:
        raise CodecError(f'Pas un .bel ES-8 (attendu "target": "{BEL_TARGET}").')
    if document.get("format") != BEL_FORMAT:
        raise CodecError(f"Format .bel {document.get('format')!r} non pris en charge (attendu {BEL_FORMAT}).")
    patches_in = document.get("patch")
    if not isinstance(patches_in, list) or len(patches_in) != PATCH_COUNT:
        raise CodecError(f'"patch" : liste de {PATCH_COUNT} patchs attendue.')
    warnings: list[str] = []
    expected_keys = {patch_key(f.name): f.name for f in PATCH_FIELDS}

    patches: dict[str, dict] = {}
    for index, entry in enumerate(patches_in):
        if set(entry) != set(expected_keys):
            diff = set(entry) ^ set(expected_keys)
            raise CodecError(f"Patch {patch_label(index)} : clés inattendues ou manquantes {sorted(diff)}.")
        if index not in base.patches:
            warnings.append(f"{patch_label(index)} : absent ou incomplet du dump de base, ignoré.")
            continue
        current = decode_patch(unpack_page(base.patches[index]))
        wanted = {name: _from_bel(name, entry[key]) for key, name in expected_keys.items()}
        changed = {k: v for k, v in wanted.items() if v != current[k]}
        if changed:
            patches[patch_label(index)] = changed

    changes: dict = {"patches": patches}
    system_in = document.get("system")
    if not isinstance(system_in, dict):
        raise CodecError('"system" : objet attendu.')
    known = {system_key(f.name): f.name for f in SYSTEM_FIELDS}
    unexpected = set(system_in) - set(known)
    missing = set(known) - set(system_in)
    if unexpected or missing:
        raise CodecError(f"Système : clés inattendues {sorted(unexpected)}, manquantes {sorted(missing)}.")
    if base.system is None:
        warnings.append("Le dump de base n'a pas de bloc système : système ignoré.")
    else:
        current = decode_system(base.system)
        system_changes = {
            name: system_in[key] for key, name in known.items() if system_in[key] != current[name]
        }
        if system_changes:
            changes["system"] = system_changes
    return changes, warnings
