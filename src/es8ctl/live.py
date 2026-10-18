"""Commandes directes de l'ES-8 (étape 4) : changer de patch, renommer, copier,
échanger, initialiser.

Messages repris du code de l'éditeur officiel (es_midi.js) : des DT1 à des
ID `7F xx` portant 2 octets de données, envoyés en mode éditeur (7F50).

| Action      | Messages                                                     |
|-------------|--------------------------------------------------------------|
| sélection   | 7F03 = 00 7F (mode d'affichage), puis 7F01 = n° de patch     |
| renommage   | 7F70+i = 00 <caractère i> (×16), puis 7F24 = n° cible         |
| copie       | 7F60 = n° source, puis 7F22 = n° cible                        |
| échange     | 7F60 = n° source, puis 7F23 = n° cible                        |
| init.       | 7F21 = n° cible                                               |

Aucun MIDI ici : ce module construit les messages et décrit le résultat
attendu ; l'envoi et la vérification passent par la CLI.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codec import CodecError, parse_patch_label
from .codec.roland import CMD_DT1, checksum
from .request import MODEL, editor_mode_message

NAME_LEN = 16


def dt1(addr: tuple[int, int], data: tuple[int, int], device_id: int = 0x00) -> bytes:
    body = [*addr, *data]
    return bytes([0xF0, 0x41, device_id, *MODEL, CMD_DT1, *body, checksum(body), 0xF7])


def _num(index: int) -> tuple[int, int]:
    return index >> 7, index & 0x7F


@dataclass(frozen=True)
class Operation:
    """Opération prête à l'envoi : messages (mode éditeur compris) et patchs touchés."""

    action: str
    messages: list[bytes]
    touched: list[int]  # index de patch (0-799) à sauvegarder et relire
    detail: dict

    def describe(self) -> dict:
        return {"action": self.action, **self.detail, "messages": [m.hex(" ") for m in self.messages]}


def _wrap(messages: list[bytes]) -> list[bytes]:
    return [editor_mode_message(True), *messages, editor_mode_message(False)]


def select(label: str) -> Operation:
    index = parse_patch_label(label)
    return Operation(
        "select",
        _wrap([dt1((0x7F, 0x03), (0x00, 0x7F)), dt1((0x7F, 0x01), _num(index))]),
        [],
        {"patch": label},
    )


def rename(label: str, name: str) -> Operation:
    index = parse_patch_label(label)
    if len(name) > NAME_LEN:
        raise CodecError(f"Name is {len(name)} characters long: {NAME_LEN} at most.")
    if not all(32 <= ord(c) < 127 for c in name):
        raise CodecError("Name: printable ASCII characters only.")
    padded = name.ljust(NAME_LEN)
    chars = [dt1((0x7F, 0x70 + i), (0x00, ord(c))) for i, c in enumerate(padded)]
    return Operation(
        "rename",
        _wrap([*chars, dt1((0x7F, 0x24), _num(index))]),
        [index],
        {"patch": label, "name": padded},
    )


def copy(source: str, target: str) -> Operation:
    src, dst = parse_patch_label(source), parse_patch_label(target)
    if src == dst:
        raise CodecError("Source and target are the same.")
    return Operation(
        "copy",
        _wrap([dt1((0x7F, 0x60), _num(src)), dt1((0x7F, 0x22), _num(dst))]),
        [src, dst],
        {"source": source, "target": target},
    )


def exchange(first: str, second: str) -> Operation:
    a, b = parse_patch_label(first), parse_patch_label(second)
    if a == b:
        raise CodecError("The two patches are the same.")
    return Operation(
        "exchange",
        _wrap([dt1((0x7F, 0x60), _num(a)), dt1((0x7F, 0x23), _num(b))]),
        [a, b],
        {"first": first, "second": second},
    )


def initialize(label: str) -> Operation:
    index = parse_patch_label(label)
    return Operation(
        "initialize",
        _wrap([dt1((0x7F, 0x21), _num(index))]),
        [index],
        {"patch": label},
    )


def expected_after(op: Operation, before: dict[int, bytes]) -> dict[int, bytes] | None:
    """Enregistrements de patch attendus après l'opération (domaine MIDI), si prévisibles.

    `before` : enregistrements (286 octets) des patchs touchés, lus avant.
    Rend None pour l'initialisation, dont le contenu d'usine n'est pas
    fixé par le protocole.
    """
    if op.action == "copy":
        src, dst = op.touched
        return {src: before[src], dst: before[src]}
    if op.action == "exchange":
        a, b = op.touched
        return {a: before[b], b: before[a]}
    return None
