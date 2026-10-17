"""Carte des champs d'un patch ES-8 (firmware v2) et conversion données ↔ JSON.

Source : spécification officielle Roland « ES-8 Bulk Dump Messages » v1.00
(2015, firmware v1), donnant pour chaque paramètre position, largeur et
bornes. Le firmware v2 (celui du `.bel` de l'éditeur, et de l'ES-8 étudié)
insère 27 bits avant `carry_over_loop` : `loop_position` passe de 16 à 22
valeurs (+24 bits) et trois champs `mixer_*` apparaissent (+3 bits). Il
ajoute `midi_clock_out` et `midi_transmit` en fin de page. Validation sur
les 2 × 799 patchs des fixtures : ancres confirmées par dumps
différentiels (loop_sw, master_bpm, name), valeurs par défaut identiques
à celles du `.bel`, champs dans leurs bornes, 2 bits de bourrage à zéro.

Positions en bits dans les 250 octets dépaquetés (flux MSB d'abord : le
bitOff de la spec Roland compte depuis le bit de poids fort). Les noms
reprennent les clés `ID_PATCH_*` du `.bel` en minuscules, et les valeurs
ont la même forme (entier, ou liste pour les champs multiples ; seul le
nom est une chaîne) : le JSON pivot est ainsi aligné sur le `.bel`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codec import CodecError, get_bits, set_bits

SCHEMA_VERSION = 2
FIRMWARE = "v2"


@dataclass(frozen=True)
class Field:
    """Champ de patch : `count` valeurs consécutives de `width` bits à partir de `bit`.

    `confidence` : « confirmed » (dump différentiel), « spec » (spec v1
    décalée, cohérente sur les fixtures) ou « inferred » (largeur déduite du
    décalage v2, non confirmée individuellement).
    """

    name: str
    bit: int
    width: int
    count: int
    lo: int
    hi: int
    confidence: str = "spec"
    is_list: bool = False

    @property
    def end(self) -> int:
        return self.bit + self.width * self.count


# (nom, nombre, largeur, min, max[, confiance]) dans l'ordre du flux.
# Un nombre > 1 donne une liste ; « name » est décodé en chaîne.
_LAYOUT: tuple[tuple, ...] = (
    ("loop_sw", 9, 1, 0, 1, "confirmed"),
    ("loop_position", 22, 4, 0, 15),
    ("mixer_mode", 1, 1, 0, 1, "inferred"),
    ("mixer_gain1", 1, 1, 0, 1, "inferred"),
    ("mixer_gain2", 1, 1, 0, 1, "inferred"),
    ("carry_over_loop", 9, 1, 0, 1),
    ("input_select", 1, 1, 0, 1),
    ("input_buffer", 1, 1, 0, 1),
    ("output_select", 1, 2, 0, 2),
    ("output_buffer", 1, 1, 0, 1),
    ("output_gain", 1, 2, 0, 3),
    ("ctl1", 1, 9, 0, 500),
    ("ctl2", 1, 9, 0, 500),
    ("ctl3", 1, 9, 0, 500),
    ("ctl4", 1, 9, 0, 500),
    ("ctl5", 1, 9, 0, 500),
    ("ctl6", 1, 9, 0, 500),
    ("exp1", 1, 8, 0, 129),
    ("exp2", 1, 8, 0, 129),
    ("master_bpm", 1, 9, 20, 500, "confirmed"),
    ("name", 16, 7, 0x20, 0x7E, "confirmed"),
    ("led_num1", 1, 1, 0, 1),
    ("led_num2", 1, 1, 0, 1),
    ("led_num3", 1, 1, 0, 1),
    ("led_num4", 1, 1, 0, 1),
    ("led_num5", 1, 1, 0, 1),
    ("led_num6", 1, 1, 0, 1),
    ("led_num7", 1, 1, 0, 1),
    ("led_num8", 1, 1, 0, 1),
    ("led_bank_d", 1, 1, 0, 1),
    ("led_bank_u", 1, 1, 0, 1),
    ("midi_tx_ch", 8, 5, 0, 16),
    ("midi_pc_bank_lsb", 8, 8, 0, 128),
    ("midi_pc_bank_msb", 8, 8, 0, 128),
    ("midi_pc", 8, 8, 0, 128),
    ("midi_ctl1_cc", 8, 8, 0, 128),
    ("midi_ctl1_cc_val", 8, 7, 0, 127),
    ("midi_ctl2_cc", 8, 8, 0, 128),
    ("midi_ctl2_cc_val", 8, 7, 0, 127),
    ("ctl_func", 16, 5, 0, 21),
    ("ctl_min", 16, 1, 0, 1),
    ("ctl_max", 16, 1, 0, 1),
    ("ctl_mod", 16, 1, 0, 1),
    ("exp_func", 2, 2, 0, 3),
    ("exp_min", 2, 9, 0, 500),
    ("exp_max", 2, 9, 0, 500),
    ("assign_sw", 12, 1, 0, 1),
    # v2 étend les plages de la spec v1 (0-21) : source 25 observée sur un assign actif.
    ("assign_source", 12, 5, 0, 31),
    ("assign_mode", 12, 1, 0, 1),
    ("assign_target", 12, 6, 0, 37),
    ("assign_target_cc_ch", 12, 4, 0, 15),
    ("assign_target_cc_no", 12, 7, 0, 127),
    ("assign_target_min", 12, 9, 0, 511),
    ("assign_target_max", 12, 9, 0, 511),
    ("assign_act_range_lo", 12, 7, 0, 126),
    ("assign_act_range_hi", 12, 7, 1, 127),
    ("assign_int_pedal_trigger", 12, 5, 0, 24),
    ("assign_int_pedal_trigger_cc", 12, 7, 0, 127),
    ("assign_int_pedal_time", 12, 7, 0, 100),
    ("assign_int_pedal_curve", 12, 2, 0, 2),
    # v2 : 0 observé (spec v1 : 1-120) et forme 3 (spec v1 : 0-2), sur assigns actifs.
    ("assign_wave_pedal_rate", 12, 7, 0, 120),
    ("assign_wave_pedal_form", 12, 2, 0, 3),
    ("midi_clock_out", 1, 1, 0, 1, "inferred"),
    ("midi_transmit", 8, 1, 0, 1, "inferred"),
)


def _build(layout: tuple[tuple, ...]) -> tuple[Field, ...]:
    fields, bit = [], 0
    for name, count, width, lo, hi, *rest in layout:
        fields.append(
            Field(
                name,
                bit,
                width,
                count,
                lo,
                hi,
                confidence=rest[0] if rest else "spec",
                is_list=count > 1 and name != "name",
            )
        )
        bit += count * width
    return tuple(fields)


PATCH_FIELDS = _build(_LAYOUT)
FIELDS_BY_NAME = {f.name: f for f in PATCH_FIELDS}
PATCH_BITS_USED = PATCH_FIELDS[-1].end  # 1998 : 2 bits de bourrage avant 2000


def _read(data: bytes, field: Field) -> list[int]:
    return [get_bits(data, field.bit + i * field.width, field.width) for i in range(field.count)]


def decode_patch(data: bytes) -> dict:
    """Décode tous les champs d'un patch (données dépaquetées), forme `.bel`."""
    out: dict = {}
    for field in PATCH_FIELDS:
        values = _read(data, field)
        if field.name == "name":
            out[field.name] = "".join(map(chr, values))
        else:
            out[field.name] = values if field.is_list else values[0]
    return out


def out_of_range(decoded: dict) -> list[str]:
    """Valeurs hors bornes d'un patch décodé (diagnostic, jamais bloquant au décodage)."""
    problems = []
    for field in PATCH_FIELDS:
        value = decoded[field.name]
        values = (
            [ord(c) for c in value]
            if field.name == "name"
            else value if field.is_list else [value]
        )
        for i, v in enumerate(values):
            if not field.lo <= v <= field.hi:
                where = f"{field.name}[{i}]" if field.count > 1 else field.name
                problems.append(f"{where} = {v} hors [{field.lo}, {field.hi}]")
    return problems


def _values(field: Field, value) -> list[int]:
    """Normalise une valeur JSON en liste d'entiers, avec validation stricte."""
    if field.name == "name":
        if not isinstance(value, str) or len(value) != field.count:
            raise CodecError(f"name : chaîne de {field.count} caractères attendue.")
        values = [ord(c) for c in value]
    elif field.is_list:
        if not isinstance(value, list) or len(value) != field.count:
            raise CodecError(f"{field.name} : liste de {field.count} valeurs attendue.")
        values = value
    else:
        values = [value]
    for v in values:
        if not isinstance(v, int) or isinstance(v, bool):
            raise CodecError(f"{field.name} : entiers attendus.")
        if not field.lo <= v <= field.hi:
            raise CodecError(f"{field.name} : {v} hors bornes [{field.lo}, {field.hi}].")
    return values


def encode_patch(base: bytes, fields: dict) -> bytes:
    """Écrit les champs fournis dans une copie de `base` (données dépaquetées).

    Les bits hors des champs fournis sont repris de `base` : un patch
    décodé puis ré-encodé est identique bit à bit. Champ inconnu ou valeur
    hors bornes = erreur, rien n'est écrit.
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
