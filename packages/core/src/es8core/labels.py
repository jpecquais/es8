"""Libellés d'affichage des valeurs, pour l'interface web.

Listes de valeurs reprises de la base de paramètres de l'éditeur BOSS officiel
(es_parameter.js), en anglais comme toute l'interface. Index = valeur stockée.
Les noms symboliques pour le CLI et les agents restent dans names.py.
"""

from __future__ import annotations

from .names import ASSIGN_SOURCES, ASSIGN_TARGETS, CTL_FUNCTIONS, CTL_SLOTS, LOOPS

OFF_ON = ["Off", "On"]


def _nums(first: int, last: int) -> list[str]:
    return [str(n) for n in range(first, last + 1)]


LOOP_LABELS = {loop: ("Volume" if loop == "LV" else f"Loop {loop[1:]}") for loop in LOOPS}

CTL_SLOT_LABELS = {
    "MEM_MAN": "Memory/Manual", "MUTE": "Mute", "BANK_D": "Bank ▼", "BANK_U": "Bank ▲",
    **{f"NUM_{n}": f"Number {n}" for n in range(1, 9)},
    **{f"CTL_IN_{n}": f"CTL In {n}" for n in range(1, 5)},
}
assert set(CTL_SLOT_LABELS) == set(CTL_SLOTS)

CTL_FUNCTION_LABELS = [
    "Off", "Memory/Manual", "Mute", "Bank down", "Bank up", "Patch up", "Patch down",
    *[f"Number {n}" for n in range(1, 9)],
    *[f"CTL {n}" for n in range(1, 7)],
    "BPM (tap tempo)",
]
assert len(CTL_FUNCTION_LABELS) == len(CTL_FUNCTIONS)

# Fonction de chaque pied dans un patch d'usine (ctl_func) : un pied, sa fonction.
FACTORY_CTL_FUNC = [
    CTL_FUNCTIONS.index(f)
    for f in ("MEM_M", "MUTE", "BANK_D", "BANK_U", *(f"NUM_{n}" for n in range(1, 9)),
              "CTL_1", "CTL_2", "CTL_3", "CTL_4")
]

ASSIGN_SOURCE_LABELS = [
    "CTL 1", "CTL 2", "CTL 3", "CTL 4", "Memory/Manual", "Mute", "Bank ▼", "Bank ▲",
    *[f"Number {n}" for n in range(1, 9)],
    "Current number", "EXP 1", "EXP 2", "Internal pedal", "Wave pedal", "Received MIDI CC",
]
assert len(ASSIGN_SOURCE_LABELS) == len(ASSIGN_SOURCES)

ASSIGN_TARGET_LABELS = [
    *[LOOP_LABELS[loop] for loop in LOOPS],
    *[f"CTL {n}" for n in range(1, 7)], "EXP 1", "EXP 2",
    "Input", "Output", "Memory/Manual", "Mute", "Bypass", "MIDI (CC)", "Tempo", "Tap tempo",
    "LED Memory/Manual", "LED Mute", "LED Bypass", "LED Bank ▼", "LED Bank ▲",
    *[f"LED Number {n}" for n in range(1, 9)],
    *[f"Patch MIDI {n}" for n in range(1, 9)],
]
assert len(ASSIGN_TARGET_LABELS) == len(ASSIGN_TARGETS)


def _target_values(name: str) -> list[str] | None:
    """Valeurs possibles de assign_target_min/max selon la cible ; None = nombre."""
    if name in ("EXP1", "EXP2", "MIDI"):
        return None  # 0-127
    if name == "MASTER_BPM":
        return None  # 20-250
    return {"IN": ["1", "2"], "OUT": ["1", "2", "1 & 2"], "MEM_M": ["Memory", "Manual"]}.get(name, OFF_ON)


ASSIGN_TARGET_VALUES = [_target_values(t) for t in ASSIGN_TARGETS]

# Divisions de tempo (valeurs 1-13) des CTL en mode TP et de la vitesse de l'onde.
TEMPO_DIVISIONS = {1: "1/1", 2: "1/2 D", 3: "1/1 T", 4: "1/2", 5: "1/4 D", 6: "1/2 T", 7: "1/4",
                   8: "1/8 D", 9: "1/4 T", 10: "1/8", 11: "1/16 D", 12: "1/8 T", 13: "1/16"}

INT_PEDAL_TRIGGERS = [
    "Patch change", "EXP 1 low", "EXP 1 mid", "EXP 1 high", "EXP 2 low", "EXP 2 mid", "EXP 2 high",
    "CTL 1", "CTL 2", "CTL 3", "CTL 4", "Memory/Manual", "Mute", "Bank ▼", "Bank ▲",
    *[f"Number {n}" for n in range(1, 9)], "Current number", "MIDI CC",
]

PATCH_VALUE_LABELS: dict[str, list[str]] = {
    "input_select": ["1", "2"],
    "input_buffer": OFF_ON,
    "output_select": ["1", "2", "1 & 2"],
    "output_buffer": OFF_ON,
    "output_gain": ["0 dB", "+2 dB", "+4 dB", "+6 dB"],
    "mixer_mode": ["Auto", "Manual"],
    "mixer_gain1": ["−6 dB", "0 dB"],
    "mixer_gain2": ["−6 dB", "0 dB"],
    "midi_clock_out": ["System", "Off"],
    "midi_transmit": ["Auto", "Manual"],
    "assign_mode": ["Momentary", "Toggle"],
    "assign_int_pedal_curve": ["Linear", "Slow", "Fast"],
    "assign_wave_pedal_form": ["Saw", "Triangle", "Sine"],
    "exp_func": ["Off", "EXP 1", "EXP 2", "BPM"],
    "ctl_mod": ["Momentary", "Toggle"],
    "midi_tx_ch": ["Off", *_nums(1, 16)],
    "midi_pc": ["Off", *_nums(0, 127)],
    "midi_pc_bank_msb": ["Off", *_nums(0, 127)],
    "midi_pc_bank_lsb": ["Off", *_nums(0, 127)],
    "assign_int_pedal_trigger": INT_PEDAL_TRIGGERS,
    "assign_int_pedal_trigger_cc": [f"CC {n}" for n in range(128)],
    "exp1": [*_nums(0, 127), "EXP 1 pedal", "EXP 2 pedal"],
    "exp2": [*_nums(0, 127), "EXP 1 pedal", "EXP 2 pedal"],
    "midi_ctl1_cc": ["Off", *(f"CC {n}" for n in range(128))],
    "midi_ctl2_cc": ["Off", *(f"CC {n}" for n in range(128))],
    **{f"led_{k}": OFF_ON for k in ("num1", "num2", "num3", "num4", "num5", "num6", "num7", "num8", "bank_d", "bank_u")},
}

SYSTEM_VALUE_LABELS: dict[str, list[str]] = {
    "play_option_sw_mode": ["On press", "On release"],
    "play_option_bank_change_mode": ["Wait", "Immediate"],
    **{f"play_option_ext_ctl_type_ctl{n}": ["Latch", "Pulse", "Inverted", "TP2", "TP3", "TP4"] for n in range(1, 7)},
    "preference_input_select": ["Patch", "1", "2"],
    "preference_input_buffer": ["Patch", "Off", "On"],
    "preference_output_select": ["Patch", "1", "2", "1 & 2"],
    "preference_output_buffer": ["Patch", "Off", "On"],
    "preference_loop7_return_mode": ["Mono", "Stereo"],
    "preference_loop8_return_mode": ["Mono", "Stereo"],
    "preference_volume_loop_lift": ["Ground", "Lift"],
    "midi_setting_midi_out_mode": ["Out", "Thru"],
    "midi_setting_rx_ch": _nums(1, 16),
    "midi_setting_device_id": _nums(1, 32),
    "midi_setting_sync_clock": ["Internal", "Auto"],
    "midi_setting_clock_out": OFF_ON,
    "others_lcd_contrast": _nums(1, 10),
    **{f"others_{k}_polarity": ["Standard", "Inverted"] for k in ("exp1", "exp2", "ctl1", "ctl2", "ctl3", "ctl4")},
    **{f"manual_number{n}": ["Off", *_nums(1, 8)] for n in range(1, 9)},
    "tempo_hold": OFF_ON,
    "link": ["Off", "On", "Auto"],
    "panel_lock": OFF_ON,
    "memory_manual": ["Memory", "Manual"],
    "ctl_sw": ["Patch", "System"],
    "exp_sw": ["Patch", "System"],
    "ctl_mod": ["Momentary", "Toggle"],
    "exp_func": ["Off", "EXP 1", "EXP 2", "BPM"],
}

# Écran Système : groupes et libellés des champs, dans l'ordre des menus de l'ES-8.
SYSTEM_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Play options", [
        ("play_option_sw_mode", "Switches trigger"),
        ("play_option_bank_change_mode", "Bank change"),
        ("play_option_bank_extent_min", "First bank"),
        ("play_option_bank_extent_max", "Last bank"),
        ("play_option_patch_change_time", "Patch change time"),
        *[(f"play_option_ext_ctl_type_ctl{n}", f"External CTL {n} type") for n in range(1, 7)],
    ]),
    ("Preferences", [
        ("preference_input_select", "Input"),
        ("preference_input_buffer", "Input buffer"),
        ("preference_output_select", "Output"),
        ("preference_output_buffer", "Output buffer"),
        ("preference_loop7_return_mode", "Loop 7 return"),
        ("preference_loop8_return_mode", "Loop 8 return"),
        ("preference_volume_loop_lift", "Volume loop ground"),
        ("preference_memory_manual_sw_mode", "Memory/Manual switch mode"),
        ("preference_mute_bypass_sw_mode", "Mute/Bypass switch mode"),
    ]),
    ("Manual mode", [
        *[(f"manual_number{n}", f"Number {n} switches loop") for n in range(1, 9)],
        ("tempo_hold", "Tempo hold"),
        ("link", "Link"),
    ]),
    ("MIDI", [
        ("midi_setting_midi_out_mode", "MIDI OUT jack"),
        ("midi_setting_rx_ch", "Receive channel"),
        ("midi_setting_device_id", "Device ID"),
        ("midi_setting_sync_clock", "Clock source"),
        ("midi_setting_clock_out", "Clock out"),
    ]),
    ("Other", [
        ("others_lcd_contrast", "Display contrast"),
        ("panel_lock", "Panel lock"),
        *[(f"others_{k}_polarity", f"{k.upper()} polarity") for k in ("exp1", "exp2", "ctl1", "ctl2", "ctl3", "ctl4")],
    ]),
]


def ui_labels() -> dict:
    """Tout ce dont l'interface a besoin pour afficher des noms plutôt que des nombres (en anglais)."""
    return {
        "loops": list(LOOPS),
        "loop_labels": LOOP_LABELS,
        "ctl_slots": list(CTL_SLOTS),
        "ctl_slot_labels": CTL_SLOT_LABELS,
        "ctl_functions": list(CTL_FUNCTIONS),
        "ctl_function_labels": CTL_FUNCTION_LABELS,
        "factory_ctl_func": FACTORY_CTL_FUNC,
        "assign_sources": list(ASSIGN_SOURCES),
        "assign_source_labels": ASSIGN_SOURCE_LABELS,
        "assign_targets": list(ASSIGN_TARGETS),
        "assign_target_labels": ASSIGN_TARGET_LABELS,
        "assign_target_values": ASSIGN_TARGET_VALUES,
        "patch_values": PATCH_VALUE_LABELS,
        "tempo_divisions": TEMPO_DIVISIONS,
        "system_values": SYSTEM_VALUE_LABELS,
        "system_groups": SYSTEM_GROUPS,
    }
