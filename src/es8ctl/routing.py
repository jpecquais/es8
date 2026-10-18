"""Chaîne de loops d'un patch (`loop_position`) ↔ notation de l'écran de l'ES-8.

`loop_position` (22 valeurs) donne l'ordre de la chaîne, confirmé sur
l'appareil (patchs 0-3, 0-8, 6-2) :

- 0 = V, 1-8 = L1-L8 ;
- 10 / 11 / 12 = début / séparateur / fin d'une branche parallèle,
  13 / 14 / 15 = idem pour le second jeu de marqueurs (deux exemplaires
  de chaque marqueur sont disponibles) ;
- 9 termine la chaîne ; les marqueurs inutilisés suivent, rangés par jeu
  (10 11 12 …, puis 13 14 15 …), comme sur tous les patchs observés.

Notation : `V8746(3//5)21`. L'ES-8 affiche les deux branches d'un parallèle
dans l'ordre inverse de la liste (liste `10 5 11 3 12` → écran `(3//5)`).
Les parallèles du second jeu (13-15) sont notés entre crochets `[a//b]` ;
leur affichage sur l'appareil n'a pas encore été observé.
"""

from __future__ import annotations

from collections import Counter

from .codec import CodecError

V, END = 0, 9
OPEN_A, SEP_A, CLOSE_A = 10, 11, 12
OPEN_B, SEP_B, CLOSE_B = 13, 14, 15
POSITION_COUNT = 22
_MARKER_SETS = ((OPEN_A, SEP_A, CLOSE_A), (OPEN_B, SEP_B, CLOSE_B))
_EXPECTED = Counter([*range(10), *range(10, 16), *range(10, 16)])

_SYMBOL = {V: "V", OPEN_A: "(", CLOSE_A: ")", OPEN_B: "[", CLOSE_B: "]"}
_SYMBOL.update({k: str(k) for k in range(1, 9)})


def _check(positions: list[int]) -> None:
    if len(positions) != POSITION_COUNT or Counter(positions) != _EXPECTED:
        raise CodecError(
            "loop_position invalide : 0-9 une fois chacun, 10-15 deux fois chacun attendus."
        )


def chain(positions: list[int]) -> list[int]:
    """Partie active de la liste : tout ce qui précède le 9."""
    _check(positions)
    return positions[: positions.index(END)]


def _render(seq: list[int]) -> str:
    out, i = [], 0
    while i < len(seq):
        token = seq[i]
        if token in (OPEN_A, OPEN_B):
            sep, close = (SEP_A, CLOSE_A) if token == OPEN_A else (SEP_B, CLOSE_B)
            depth, j, split = 0, i, None
            while True:  # fin du parallèle correspondant
                if seq[j] == token:
                    depth += 1
                elif seq[j] == close:
                    depth -= 1
                    if depth == 0:
                        break
                elif seq[j] == sep and depth == 1:
                    split = j
                j += 1
            if split is None:
                raise CodecError("Parallèle sans séparateur dans loop_position.")
            first, second = _render(seq[i + 1 : split]), _render(seq[split + 1 : j])
            out.append(f"{_SYMBOL[token]}{second}//{first}{_SYMBOL[close]}")  # ordre de l'écran
            i = j + 1
        elif token in _SYMBOL and token not in (CLOSE_A, CLOSE_B):
            out.append(_SYMBOL[token])
            i += 1
        else:
            raise CodecError(f"Marqueur inattendu {token} dans loop_position.")
    return "".join(out)


def render(positions: list[int]) -> str:
    """`loop_position` → notation de l'écran, ex. « V8746(3//5)21 »."""
    return _render(chain(positions))


def _parse(text: str, i: int, stop: str | None) -> tuple[list[int], int]:
    seq: list[int] = []
    while i < len(text):
        c = text[i]
        if stop is not None and text.startswith(stop, i):
            return seq, i
        if c in "([":
            close = ")" if c == "(" else "]"
            opener, sep, closer = _MARKER_SETS[0] if c == "(" else _MARKER_SETS[1]
            second, i = _parse(text, i + 1, "//")
            if not text.startswith("//", i):
                raise CodecError(f"Parallèle sans « // » dans {text!r}.")
            first, i = _parse(text, i + 2, close)
            if i >= len(text) or text[i] != close:
                raise CodecError(f"Parallèle non fermé dans {text!r}.")
            seq += [opener, *first, sep, *second, closer]  # écran → ordre de la liste
            i += 1
        elif c.upper() == "V":
            seq.append(V)
            i += 1
        elif c in "12345678":
            seq.append(int(c))
            i += 1
        elif c in " -":
            i += 1
        else:
            raise CodecError(f"Caractère inattendu {c!r} dans la chaîne {text!r}.")
    if stop is not None:
        raise CodecError(f"Chaîne incomplète : {text!r}.")
    return seq, i


def parse(text: str, base: list[int] | None = None) -> list[int]:
    """Notation de l'écran → `loop_position` complet (22 valeurs).

    Les 8 loops et V doivent apparaître exactement une fois ; chaque jeu de
    marqueurs au plus deux fois. Les marqueurs inutilisés sont rangés après
    le 9 : dans l'ordre de `base` si fourni (patch modifié), sinon par jeu.
    """
    seq, _ = _parse(text.strip(), 0, None)
    loops = [t for t in seq if t <= 8]
    if sorted(loops) != list(range(9)):
        raise CodecError(f"La chaîne {text!r} doit contenir V et 1-8 exactement une fois.")
    remaining = _EXPECTED - Counter(seq) - Counter(range(10))
    if any(v < 0 for v in (Counter(seq) - _EXPECTED).values()) or (Counter(seq) - _EXPECTED):
        raise CodecError(f"Trop de parallèles dans {text!r} (deux par jeu au plus).")
    if base is not None:
        try:
            return with_chain(base, seq)
        except ValueError:
            raise CodecError(f"Trop de parallèles dans {text!r} (deux par jeu au plus).") from None
    tail = []
    for markers in _MARKER_SETS:
        for _ in range(remaining[markers[0]]):
            tail += list(markers)
    positions = [*seq, END, *tail]
    _check(positions)
    return positions


def with_chain(positions: list[int], new_chain: list[int]) -> list[int]:
    """Remplace la partie active ; garde l'ordre d'origine des marqueurs inutilisés.

    L'ordre de la réserve varie d'un patch à l'autre sur l'appareil ; le
    conserver évite de réécrire des bits sans raison.
    """
    _check(positions)
    need = _EXPECTED - Counter(range(10)) - Counter(new_chain)
    if Counter(t for t in new_chain if t > END) - (_EXPECTED - Counter(range(10))):
        raise ValueError("trop de marqueurs")
    spare = []
    for token in positions[positions.index(END) + 1 :]:  # ordre d'origine d'abord
        if need[token] > 0:
            spare.append(token)
            need[token] -= 1
    for markers in _MARKER_SETS:  # marqueurs libérés : ajoutés par jeu
        while need[markers[0]] > 0:
            spare += list(markers)
            for m in markers:
                need[m] -= 1
    rebuilt = [*new_chain, END, *spare]
    _check(rebuilt)
    return rebuilt


def swap_loops(positions: list[int], a: int, b: int) -> list[int]:
    """Échange deux loops (valeurs 0-8 : 0 = V) dans la chaîne."""
    _check(positions)
    swap = {a: b, b: a}
    return [swap.get(v, v) if v <= 8 else v for v in positions]
