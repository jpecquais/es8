"""Carte du bloc système ES-8 (firmware v2) et conversion pages ↔ JSON.

Le bloc système = 8 pages de 250 octets (messages 00 00 – 00 0F).

- Page 1 : réglages. Bits 0–84 conformes à la spec Roland v1. Le v2 y
  ajoute ensuite les fonctions CTL/EXP du mode manuel (`ctl_sw` … `exp_max`),
  aux largeurs de leurs équivalents de patch : lecture cohérente avec les
  défauts du `.bel` (`ctl_sw` [0, 1, 0…], `ctl_func` [1, 2, 3, 4, 7…]).
  Puis `manual_number1-8` (4 bits), `tempo_hold` et `link` (bits 271–305),
  positions tirées de la base de paramètres de l'éditeur officiel (prmdb).
- Pages 2–8 : `pc_map_bank0_pc` … `pc_map_bank6_pc`, 128 × 10 bits chacune :
  patch (0–799) rappelé par chaque program change, par banque MIDI.

Clés : `ID_SYSTEM_*` du `.bel` en minuscules, sans le préfixe.
"""

from __future__ import annotations

from .codec import CodecError, PATCH_RECORD_LEN, pack_page, unpack_page
from .layout import Field, build_layout, decode_fields, encode_fields, out_of_range

SYSTEM_PAGES = 8
PC_MAP_ENTRIES = 128

_PAGE1: tuple[tuple, ...] = (
    ("current_num", 1, 10, 0, 799),
    ("panel_lock", 1, 1, 0, 1),
    ("play_option_sw_mode", 1, 1, 0, 1),
    ("play_option_bank_change_mode", 1, 1, 0, 1),
    *((f"play_option_ext_ctl_type_ctl{i}", 1, 3, 0, 5) for i in range(1, 7)),
    ("play_option_bank_extent_min", 1, 7, 0, 99),
    ("play_option_bank_extent_max", 1, 7, 0, 99),
    ("play_option_patch_change_time", 1, 4, 0, 10),
    ("preference_input_select", 1, 2, 0, 2),
    ("preference_input_buffer", 1, 2, 0, 2),
    ("preference_output_select", 1, 2, 0, 3),
    ("preference_output_buffer", 1, 2, 0, 2),
    ("preference_loop7_return_mode", 1, 1, 0, 1),
    ("preference_loop8_return_mode", 1, 1, 0, 1),
    ("preference_volume_loop_lift", 1, 1, 0, 1),
    ("midi_setting_midi_out_mode", 1, 1, 0, 1),
    ("midi_setting_rx_ch", 1, 4, 0, 15),
    ("midi_setting_device_id", 1, 5, 0, 31),
    ("midi_setting_sync_clock", 1, 1, 0, 1),
    ("midi_setting_clock_out", 1, 1, 0, 1),
    ("others_lcd_contrast", 1, 4, 0, 9),
    ("others_exp1_polarity", 1, 1, 0, 1),
    ("others_exp2_polarity", 1, 1, 0, 1),
    ("others_ctl1_polarity", 1, 1, 0, 1),
    ("others_ctl2_polarity", 1, 1, 0, 1),
    ("others_ctl3_polarity", 1, 1, 0, 1),
    ("others_ctl4_polarity", 1, 1, 0, 1),
    ("preference_memory_manual_sw_mode", 1, 1, 0, 1),
    ("preference_mute_bypass_sw_mode", 1, 1, 0, 1),
    ("memory_manual", 1, 1, 0, 1),
    # Extension v2 (mode manuel) ; confirmée par la base de l'éditeur officiel.
    ("ctl_sw", 16, 1, 0, 1, "official"),
    ("ctl_func", 16, 5, 0, 21, "official"),
    ("ctl_min", 16, 1, 0, 1, "official"),
    ("ctl_max", 16, 1, 0, 1, "official"),
    ("ctl_mod", 16, 1, 0, 1, "official"),
    ("exp_sw", 2, 1, 0, 1, "official"),
    ("exp_func", 2, 2, 0, 3, "official"),
    ("exp_min", 2, 9, 0, 500, "official"),
    ("exp_max", 2, 9, 0, 500, "official"),
    *((f"manual_number{i}", 1, 4, 0, 9, "official") for i in range(1, 9)),
    ("tempo_hold", 1, 1, 0, 1, "official"),
    ("link", 1, 2, 0, 2, "official"),  # OFF / ON / AUTO
)

PAGE_FIELDS: tuple[tuple[Field, ...], ...] = (
    build_layout(_PAGE1),
    *(
        build_layout(((f"pc_map_bank{bank}_pc", PC_MAP_ENTRIES, 10, 0, 799),))
        for bank in range(SYSTEM_PAGES - 1)
    ),
)
SYSTEM_FIELDS: tuple[Field, ...] = tuple(f for page in PAGE_FIELDS for f in page)


def split_pages(system: bytes) -> list[bytes]:
    """Découpe le bloc système (16 trames MIDI) en 8 pages dépaquetées."""
    if len(system) != SYSTEM_PAGES * PATCH_RECORD_LEN:
        raise CodecError(
            f"System block is {len(system)} MIDI bytes, expected {SYSTEM_PAGES * PATCH_RECORD_LEN}."
        )
    return [
        unpack_page(system[i * PATCH_RECORD_LEN : (i + 1) * PATCH_RECORD_LEN])
        for i in range(SYSTEM_PAGES)
    ]


def decode_system(system: bytes) -> dict:
    """Décode le bloc système (domaine MIDI, tel que `BulkDump.system`)."""
    out: dict = {}
    for page, fields in zip(split_pages(system), PAGE_FIELDS):
        out.update(decode_fields(page, fields))
    return out


def system_out_of_range(decoded: dict) -> list[str]:
    return out_of_range(decoded, SYSTEM_FIELDS)


def encode_system(base: bytes, values: dict) -> bytes:
    """Écrit `values` dans une copie du bloc système `base` (domaine MIDI).

    Les bits non fournis sont conservés. Champ inconnu ou valeur hors
    bornes = erreur.
    """
    known = {f.name for f in SYSTEM_FIELDS}
    unknown = set(values) - known
    if unknown:
        raise CodecError(f"Unknown fields: {', '.join(sorted(unknown))}.")
    pages = split_pages(base)
    out = []
    for page, fields in zip(pages, PAGE_FIELDS):
        names = {f.name for f in fields}
        mine = {k: v for k, v in values.items() if k in names}
        out.append(pack_page(encode_fields(page, fields, mine)))
    return b"".join(out)
