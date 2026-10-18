"""Transformations en masse : dump de base + opération → changements JSON pour `apply`.

Une transformation ne touche jamais au MIDI : elle produit le même format
de changements que `apply` consomme (simulation, sauvegarde et
vérification restent donc au même endroit). Seuls les patchs réellement
modifiés figurent dans le résultat.

Opérations :
- `set` : affectations `champ=valeur` ou `champ[index]=valeur` sur une
  sélection de patchs (index et valeurs symboliques acceptés, cf. names.py) ;
- `swap_loops` : échange deux loops partout (interrupteurs, carry-over,
  cibles d'assign, place dans la chaîne), pour refléter un échange de câbles.
"""

from __future__ import annotations

import re

from .codec import BulkDump, CodecError, parse_patch_label, patch_label, unpack_page
from .names import LOOPS, resolve_index, resolve_value
from .patch import FIELDS_BY_NAME, decode_patch
from .routing import swap_loops as swap_in_chain

_ASSIGNMENT = re.compile(r"^\s*([a-z0-9_]+)\s*(?:\[\s*([^\]]+?)\s*\])?\s*=\s*(.*?)\s*$", re.S)

# Champs indexés par loop (L1…L8, LV) et champ dont les valeurs désignent des loops.
LOOP_INDEXED_FIELDS = ("loop_sw", "carry_over_loop")
LOOP_VALUED_FIELDS = ("assign_target",)


def select_patches(dump: BulkDump, spec: str | None) -> list[int]:
    """Sélection : « all » (défaut), « 0-1..9-8 », « 0-1,2-3 », combinables.

    Seuls les patchs complets dans le dump sont sélectionnables ; en
    demander un absent est une erreur explicite.
    """
    if spec is None or spec.strip().lower() == "all":
        return sorted(dump.patches)
    chosen: set[int] = set()
    for part in spec.split(","):
        bounds = [parse_patch_label(b.strip()) for b in part.split("..")]
        if len(bounds) not in (1, 2) or bounds[0] > bounds[-1]:
            raise CodecError(f"Sélection invalide : {part!r} (ex. 0-1..9-8).")
        chosen.update(range(bounds[0], bounds[-1] + 1))
    missing = [patch_label(i) for i in sorted(chosen) if i not in dump.patches]
    if missing:
        raise CodecError(f"Patch(s) absent(s) ou incomplet(s) dans le dump : {', '.join(missing)}.")
    return sorted(chosen)


def parse_assignment(text: str) -> tuple[str, int | None, int | str]:
    """« ctl_func[NUM_8]=BPM » → ("ctl_func", 11, 21)."""
    match = _ASSIGNMENT.match(text)
    if not match:
        raise CodecError(f"Affectation invalide : {text!r} (ex. master_bpm=120, ctl_func[NUM_8]=BPM).")
    name, index, value = match.groups()
    field = FIELDS_BY_NAME.get(name)
    if field is None:
        raise CodecError(f"Champ inconnu : {name!r}.")
    if index is not None:
        if not field.is_list:
            raise CodecError(f"{name} n'est pas une liste : pas d'index.")
        position = resolve_index(name, index)
        if not 0 <= position < field.count:
            raise CodecError(f"Index {position} hors de {name}[0..{field.count - 1}].")
        return name, position, resolve_value(name, value)
    if field.is_list:
        raise CodecError(f"{name} est une liste de {field.count} valeurs : préciser un index.")
    return name, None, resolve_value(name, value)


def _collect(dump: BulkDump, indices: list[int], edit) -> dict:
    """Applique `edit(champs décodés) -> champs modifiés` ; ne garde que les vrais changements."""
    patches: dict[str, dict] = {}
    for index in indices:
        before = decode_patch(unpack_page(dump.patches[index]))
        after = edit({k: list(v) if isinstance(v, list) else v for k, v in before.items()})
        changed = {k: v for k, v in after.items() if v != before[k]}
        if changed:
            patches[patch_label(index)] = changed
    return {"patches": patches}


def op_set(dump: BulkDump, indices: list[int], assignments: list[str]) -> dict:
    parsed = [parse_assignment(a) for a in assignments]
    if not parsed:
        raise CodecError("Aucune affectation fournie.")

    def edit(fields: dict) -> dict:
        for name, index, value in parsed:
            if index is None:
                fields[name] = value
            else:
                fields[name][index] = value
        return fields

    return _collect(dump, indices, edit)


def _loop_index(token: str) -> int:
    token = token.strip().upper()
    if token in LOOPS:
        return LOOPS.index(token)
    if token.isdigit() and 1 <= int(token) <= 8:
        return int(token) - 1
    raise CodecError(f"Loop inconnue : {token!r} (1-8, L1…L8 ou LV).")


def _chain_value(loop_index: int) -> int:
    """Index LOOPS (L1…L8 = 0-7, LV = 8) → valeur dans loop_position (V = 0, Lk = k)."""
    return 0 if LOOPS[loop_index] == "LV" else loop_index + 1


def op_swap_loops(dump: BulkDump, indices: list[int], a: str, b: str) -> dict:
    """Échange deux loops : interrupteurs, carry-over, cibles d'assign et chaîne.

    Reflète un échange de câbles : chaque patch garde le même son.
    """
    ia, ib = _loop_index(a), _loop_index(b)
    if ia == ib:
        raise CodecError("Les deux loops à échanger sont identiques.")

    def edit(fields: dict) -> dict:
        for name in LOOP_INDEXED_FIELDS:
            fields[name][ia], fields[name][ib] = fields[name][ib], fields[name][ia]
        for name in LOOP_VALUED_FIELDS:
            fields[name] = [ib if v == ia else ia if v == ib else v for v in fields[name]]
        fields["loop_position"] = swap_in_chain(
            fields["loop_position"], _chain_value(ia), _chain_value(ib)
        )
        return fields

    return _collect(dump, indices, edit)


FACTORY_NAME = "BOSS ES-8       "


def op_variants(
    dump: BulkDump,
    source: str,
    into: str,
    count: int,
    seed: int = 0,
    prefix: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Génère `count` copies du patch `source` aux routings tous différents.

    Les loops (L1-L8) permutent entre elles dans la chaîne ; V, les
    parallèles et leurs marqueurs restent en place, de même que tous les
    autres réglages (interrupteurs compris : chaque loop garde son état).
    Les variantes vont dans les patchs consécutifs à partir de `into`,
    nommées `<préfixe><n°>`. Déterministe pour une graine donnée.
    """
    import random
    from itertools import permutations
    from math import factorial

    src = parse_patch_label(source)
    if src not in dump.patches:
        raise CodecError(f"Patch source {source} absent ou incomplet dans le dump.")
    start = parse_patch_label(into)
    targets = list(range(start, start + count))
    if count < 1 or targets[-1] >= 800:
        raise CodecError(f"{count} variante(s) à partir de {into} : dépasse 99-8.")
    if src in targets:
        raise CodecError("La plage cible contient le patch source.")
    missing = [patch_label(i) for i in targets if i not in dump.patches]
    if missing:
        raise CodecError(f"Patch(s) cible(s) absent(s) ou incomplet(s) : {', '.join(missing)}.")

    base = decode_patch(unpack_page(dump.patches[src]))
    positions = base["loop_position"]
    end = positions.index(9)
    slots = [i for i in range(end) if 1 <= positions[i] <= 8]
    loops = [positions[i] for i in slots]
    available = factorial(len(loops)) - 1  # toutes les permutations sauf l'originale
    if count > available:
        raise CodecError(f"{count} variantes demandées, {available} routings distincts possibles.")

    rng = random.Random(seed)
    seen = {tuple(loops)}
    orders: list[tuple[int, ...]] = []
    if available <= 5040:  # petit espace : énumérer, puis tirer sans remise
        pool = [p for p in permutations(loops) if p not in seen]
        orders = rng.sample(pool, count)
    else:
        while len(orders) < count:
            candidate = tuple(rng.sample(loops, len(loops)))
            if candidate not in seen:
                seen.add(candidate)
                orders.append(candidate)

    stem = (prefix if prefix is not None else base["name"].rstrip()[:13] + " ")[:16]
    width = len(str(count))
    patches: dict[str, dict] = {}
    for n, (target, order) in enumerate(zip(targets, orders), start=1):
        current = decode_patch(unpack_page(dump.patches[target]))
        if not overwrite and current["name"] != FACTORY_NAME:
            raise CodecError(
                f"Le patch cible {patch_label(target)} « {current['name'].rstrip()} » n'est pas "
                "vierge : choisir une autre plage ou passer --overwrite."
            )
        new_positions = list(positions)
        for slot, loop in zip(slots, order):
            new_positions[slot] = loop
        suffix = str(n).zfill(width)
        name = (stem[: 16 - len(suffix)] + suffix).ljust(16)
        wanted = {**base, "loop_position": new_positions, "name": name}
        changed = {k: v for k, v in wanted.items() if v != current[k]}
        if changed:
            patches[patch_label(target)] = changed
    return {"patches": patches}
