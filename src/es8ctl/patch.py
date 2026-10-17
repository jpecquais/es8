"""Carte des champs d'un patch ES-8 et conversion données dépaquetées ↔ JSON.

Positions en bits dans les 250 octets dépaquetés (flux MSB d'abord), établies
par dumps différentiels — voir docs/bulk-format.md. Seuls les champs
confirmés figurent ici ; les bits non cartographiés sont conservés tels
quels par `encode_patch`, qui part toujours des données d'origine.

Les noms de champs reprennent ceux du `.bel` de l'éditeur officiel
(`ID_PATCH_LOOP_SW` → `loop_sw`), dont l'ordre est aussi celui du flux.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codec import CodecError, get_bits, set_bits

SCHEMA_VERSION = 1

LOOP_NAMES = ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "LV")


@dataclass(frozen=True)
class Field:
    """Champ de patch : `count` valeurs consécutives de `width` bits à partir de `bit`."""

    name: str
    bit: int
    width: int
    count: int = 1
    kind: str = "int"  # int · bool · ascii

    @property
    def end(self) -> int:
        return self.bit + self.width * self.count


PATCH_FIELDS = (
    Field("loop_sw", bit=0, width=1, count=9, kind="bool"),
    Field("loop_position", bit=9, width=4, count=22),
    Field("master_bpm", bit=186, width=9),
    Field("name", bit=195, width=7, count=16, kind="ascii"),
)
FIELDS_BY_NAME = {f.name: f for f in PATCH_FIELDS}


def _read(data: bytes, field: Field) -> list[int]:
    return [get_bits(data, field.bit + i * field.width, field.width) for i in range(field.count)]


def decode_patch(data: bytes) -> dict:
    """Décode les champs connus d'un patch (données dépaquetées)."""
    out: dict = {}
    for field in PATCH_FIELDS:
        values = _read(data, field)
        if field.name == "loop_sw":
            out[field.name] = {loop: bool(v) for loop, v in zip(LOOP_NAMES, values)}
        elif field.kind == "ascii":
            out[field.name] = "".join(map(chr, values))
        elif field.count == 1:
            out[field.name] = values[0]
        else:
            out[field.name] = values
    return out


def _values(field: Field, value) -> list[int]:
    """Normalise une valeur JSON en liste d'entiers, avec validation stricte."""
    if field.name == "loop_sw":
        if not isinstance(value, dict) or set(value) != set(LOOP_NAMES):
            raise CodecError(f"loop_sw : clés attendues {', '.join(LOOP_NAMES)}.")
        values = [value[loop] for loop in LOOP_NAMES]
        if not all(isinstance(v, bool) for v in values):
            raise CodecError("loop_sw : valeurs booléennes attendues.")
        return [int(v) for v in values]
    if field.kind == "ascii":
        if not isinstance(value, str) or len(value) != field.count:
            raise CodecError(f"{field.name} : chaîne de {field.count} caractères attendue.")
        if not all(32 <= ord(c) < 127 for c in value):
            raise CodecError(f"{field.name} : caractères ASCII imprimables uniquement.")
        return [ord(c) for c in value]
    values = [value] if field.count == 1 else value
    if not isinstance(values, list) or len(values) != field.count:
        raise CodecError(f"{field.name} : {field.count} valeur(s) attendue(s).")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        raise CodecError(f"{field.name} : entiers attendus.")
    return values


def encode_patch(base: bytes, fields: dict) -> bytes:
    """Écrit les champs fournis dans une copie de `base` (données dépaquetées).

    Les bits hors des champs fournis sont repris de `base` : un patch
    décodé puis ré-encodé est identique bit à bit. Champ inconnu = erreur.
    """
    unknown = set(fields) - set(FIELDS_BY_NAME)
    if unknown:
        raise CodecError(f"Champs inconnus : {', '.join(sorted(unknown))}.")
    data = base
    for name, value in fields.items():
        field = FIELDS_BY_NAME[name]
        for i, v in enumerate(_values(field, value)):
            data = set_bits(data, field.bit + i * field.width, field.width, v)
    return data
