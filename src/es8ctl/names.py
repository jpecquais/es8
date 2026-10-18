"""Noms symboliques des index et des valeurs de champs (lisibles par un humain ou un agent).

Sources : spec Roland (index de `ctl_func`) et listes de valeurs de l'éditeur
BOSS officiel (es_parameter.js).
Permet d'écrire `ctl_func[NUM_8]=BPM` plutôt que `ctl_func[11]=21`.
"""

from __future__ import annotations

from .codec import CodecError

NAME_LEN = 16

LOOPS = ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "LV")

# Index des 16 entrées de ctl_func / ctl_min / ctl_max / ctl_mod (spec Roland).
CTL_SLOTS = (
    "MEM_MAN", "MUTE", "BANK_D", "BANK_U",
    "NUM_1", "NUM_2", "NUM_3", "NUM_4", "NUM_5", "NUM_6", "NUM_7", "NUM_8",
    "CTL_IN_1", "CTL_IN_2", "CTL_IN_3", "CTL_IN_4",
)

# Valeurs de ctl_func (0-21). BPM = tap tempo.
CTL_FUNCTIONS = (
    "OFF", "MEM_M", "MUTE", "BANK_D", "BANK_U", "MEM_U", "MEM_D",
    "NUM_1", "NUM_2", "NUM_3", "NUM_4", "NUM_5", "NUM_6", "NUM_7", "NUM_8",
    "CTL_1", "CTL_2", "CTL_3", "CTL_4", "CTL_5", "CTL_6", "BPM",
)

# Valeurs de assign_target (0-45), ordre de l'éditeur officiel (es_parameter.js).
ASSIGN_TARGETS = (
    "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "LV",
    "CTL1", "CTL2", "CTL3", "CTL4", "CTL5", "CTL6", "EXP1", "EXP2",
    "IN", "OUT", "MEM_M", "MUTE", "BYPASS", "MIDI", "MASTER_BPM", "TAP",
    "LED_MEM_M", "LED_MUTE", "LED_BYPASS", "LED_BANK_D", "LED_BANK_U",
    "LED_NUM1", "LED_NUM2", "LED_NUM3", "LED_NUM4",
    "LED_NUM5", "LED_NUM6", "LED_NUM7", "LED_NUM8",
    "PMIDI1", "PMIDI2", "PMIDI3", "PMIDI4", "PMIDI5", "PMIDI6", "PMIDI7", "PMIDI8",
)
assert len(ASSIGN_TARGETS) == 46

# Valeurs de assign_source (0-21), ordre de l'éditeur officiel. CC = CC MIDI reçu,
# dont le numéro est dans assign_int_pedal_trigger_cc (champ partagé avec INT).
ASSIGN_SOURCES = (
    "CTL1", "CTL2", "CTL3", "CTL4", "MEM_M", "MUTE", "BANK_D", "BANK_U",
    "NUM1", "NUM2", "NUM3", "NUM4", "NUM5", "NUM6", "NUM7", "NUM8",
    "CNUM", "EXP1", "EXP2", "INT", "WAV", "CC",
)
assert len(ASSIGN_SOURCES) == 22

# Noms d'index par champ (champs listes) ; noms de valeurs par champ.
INDEX_NAMES: dict[str, tuple[str, ...]] = {
    "loop_sw": LOOPS,
    "carry_over_loop": LOOPS,
    "ctl_func": CTL_SLOTS,
    "ctl_min": CTL_SLOTS,
    "ctl_max": CTL_SLOTS,
    "ctl_mod": CTL_SLOTS,
}
VALUE_NAMES: dict[str, tuple[str, ...]] = {
    "ctl_func": CTL_FUNCTIONS,
    "assign_target": ASSIGN_TARGETS,
    "assign_source": ASSIGN_SOURCES,
}


def _resolve(token: str, names: tuple[str, ...] | None, what: str) -> int:
    token = token.strip()
    if token.lstrip("-").isdigit():
        return int(token)
    if names is not None and token.upper() in names:
        return names.index(token.upper())
    known = f" (connus : {', '.join(names)})" if names else ""
    raise CodecError(f"{what} inconnu : {token!r}{known}.")


def resolve_index(field: str, token: str) -> int:
    """Index numérique ou symbolique (`NUM_8`, `L6`…) d'un champ liste."""
    return _resolve(token, INDEX_NAMES.get(field), f"Index de {field}")


def resolve_value(field: str, token: str) -> int | str:
    """Valeur numérique ou symbolique (`BPM`, `L7`…) ; `name` complété à 16 caractères."""
    if field == "name":
        if len(token) > NAME_LEN:
            raise CodecError(f"Nom de {len(token)} caractères : {NAME_LEN} au plus.")
        return token.ljust(NAME_LEN)
    return _resolve(token, VALUE_NAMES.get(field), f"Valeur de {field}")
