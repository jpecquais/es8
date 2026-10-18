"""Carte des champs d'un patch ES-8 (firmware v2) et conversion données ↔ JSON.

Source : spécification officielle Roland « ES-8 Bulk Dump Messages » v1.00
(2015, firmware v1), donnant pour chaque paramètre position, largeur et
bornes. Le firmware v2 (celui du `.bel` de l'éditeur, et de l'ES-8 étudié)
insère 27 bits avant `carry_over_loop` : `loop_position` passe de 16 à 22
valeurs (+24 bits) et trois champs `mixer_*` apparaissent (+3 bits). Il
ajoute `midi_clock_out` et `midi_transmit` en fin de page. Les bornes v1
tiennent sur toutes les valeurs observées. Validation sur
les 2 × 799 patchs des fixtures : ancres confirmées par dumps
différentiels (loop_sw, master_bpm, name), valeurs par défaut identiques
à celles du `.bel`, champs dans leurs bornes, 2 bits de bourrage à zéro.

Positions en bits dans les 250 octets de la page (`unpack_page`) (flux MSB d'abord : le
bitOff de la spec Roland compte depuis le bit de poids fort). Les noms
reprennent les clés `ID_PATCH_*` du `.bel` en minuscules, et les valeurs
ont la même forme (entier, ou liste pour les champs multiples ; seul le
nom est une chaîne) : le JSON pivot est ainsi aligné sur le `.bel`.
"""

from __future__ import annotations

from .layout import Field, build_layout, decode_fields, encode_fields
from .layout import out_of_range as _out_of_range

SCHEMA_VERSION = 2
FIRMWARE = "v2"


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
    ("assign_source", 12, 5, 0, 21),
    ("assign_mode", 12, 1, 0, 1),
    # v1 : 0-37 ; v2 ajoute PMIDI1-8 (ordre de l'éditeur, cf. names.ASSIGN_TARGETS).
    ("assign_target", 12, 6, 0, 42),
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
    ("assign_wave_pedal_rate", 12, 7, 1, 120),
    ("assign_wave_pedal_form", 12, 2, 0, 2),
    ("midi_clock_out", 1, 1, 0, 1, "inferred"),
    ("midi_transmit", 8, 1, 0, 1, "inferred"),
)


PATCH_FIELDS: tuple[Field, ...] = build_layout(_LAYOUT)
FIELDS_BY_NAME = {f.name: f for f in PATCH_FIELDS}
PATCH_BITS_USED = PATCH_FIELDS[-1].end  # 1998 : 2 bits de bourrage avant 2000


def decode_patch(data: bytes) -> dict:
    """Décode tous les champs d'un patch (page dépaquetée), forme `.bel`."""
    return decode_fields(data, PATCH_FIELDS)


def out_of_range(decoded: dict) -> list[str]:
    """Valeurs hors bornes d'un patch décodé (diagnostic, jamais bloquant au décodage)."""
    return _out_of_range(decoded, PATCH_FIELDS)


def encode_patch(base: bytes, fields: dict) -> bytes:
    """Écrit les champs fournis dans une copie de `base` (page dépaquetée).

    Les bits hors des champs fournis sont repris de `base` : un patch
    décodé puis ré-encodé est identique bit à bit. Champ inconnu ou valeur
    hors bornes = erreur, rien n'est écrit.
    """
    return encode_fields(base, PATCH_FIELDS, fields)
