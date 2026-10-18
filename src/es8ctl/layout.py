"""Mécanique commune aux pages ES-8 : champs empaquetés au bit ↔ valeurs JSON.

Une page fait 250 octets lus comme un flux de bits MSB d'abord (voir
`codec.unpack_page`). Un layout est une suite de champs contigus décrits
par (nom, nombre, largeur, min, max[, confiance]) ; les valeurs JSON ont
la forme du `.bel` de l'éditeur officiel : entier, liste d'entiers pour les
champs multiples, chaîne pour les champs texte.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codec import CodecError, get_bits, set_bits

TEXT_FIELDS = frozenset({"name"})


@dataclass(frozen=True)
class Field:
    """`count` valeurs consécutives de `width` bits à partir de `bit`.

    `confidence` : « confirmed » (dump différentiel sur l'appareil) ou
    « official » (base de paramètres `prmdb` de l'éditeur BOSS officiel, qui
    concorde entièrement avec la spec Roland recalée).
    """

    name: str
    bit: int
    width: int
    count: int
    lo: int
    hi: int
    confidence: str = "official"

    @property
    def end(self) -> int:
        return self.bit + self.width * self.count

    @property
    def is_text(self) -> bool:
        return self.name in TEXT_FIELDS

    @property
    def is_list(self) -> bool:
        return self.count > 1 and not self.is_text


def build_layout(layout: tuple[tuple, ...]) -> tuple[Field, ...]:
    """Positionne des champs contigus à partir du bit 0."""
    fields, bit = [], 0
    for name, count, width, lo, hi, *rest in layout:
        fields.append(Field(name, bit, width, count, lo, hi, rest[0] if rest else "official"))
        bit += count * width
    return tuple(fields)


def _read(data: bytes, field: Field) -> list[int]:
    return [get_bits(data, field.bit + i * field.width, field.width) for i in range(field.count)]


def decode_fields(data: bytes, fields: tuple[Field, ...]) -> dict:
    out: dict = {}
    for field in fields:
        values = _read(data, field)
        if field.is_text:
            out[field.name] = "".join(map(chr, values))
        else:
            out[field.name] = values if field.is_list else values[0]
    return out


def out_of_range(decoded: dict, fields: tuple[Field, ...]) -> list[str]:
    """Valeurs hors bornes d'une page décodée (diagnostic, jamais bloquant au décodage)."""
    problems = []
    for field in fields:
        value = decoded[field.name]
        if field.is_text:
            values = [ord(c) for c in value]
        else:
            values = value if field.is_list else [value]
        for i, v in enumerate(values):
            if not field.lo <= v <= field.hi:
                where = f"{field.name}[{i}]" if field.count > 1 else field.name
                problems.append(f"{where} = {v} is outside [{field.lo}, {field.hi}]")
    return problems


def _values(field: Field, value) -> list[int]:
    """Normalise une valeur JSON en liste d'entiers, avec validation stricte."""
    if field.is_text:
        if not isinstance(value, str) or len(value) != field.count:
            raise CodecError(f"{field.name}: expected a string of {field.count} characters.")
        values = [ord(c) for c in value]
    elif field.is_list:
        if not isinstance(value, list) or len(value) != field.count:
            raise CodecError(f"{field.name}: expected a list of {field.count} values.")
        values = value
    else:
        values = [value]
    for v in values:
        if not isinstance(v, int) or isinstance(v, bool):
            raise CodecError(f"{field.name}: expected integers.")
        if not field.lo <= v <= field.hi:
            raise CodecError(f"{field.name}: {v} is out of range [{field.lo}, {field.hi}].")
    return values


def encode_fields(base: bytes, fields: tuple[Field, ...], values: dict) -> bytes:
    """Écrit `values` dans une copie de `base` ; les bits non fournis sont conservés.

    Champ inconnu ou valeur hors bornes = erreur, rien n'est écrit.
    """
    by_name = {f.name: f for f in fields}
    unknown = set(values) - set(by_name)
    if unknown:
        raise CodecError(f"Unknown fields: {', '.join(sorted(unknown))}.")
    data = base
    for name, value in values.items():
        field = by_name[name]
        for i, v in enumerate(_values(field, value)):
            data = set_bits(data, field.bit + i * field.width, field.width, v)
    return data
