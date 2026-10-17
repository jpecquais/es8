"""Format SysEx propre au Boss ES-8, établi empiriquement.

Établi à partir de dumps réels (session hardware du 2026-10-17) :
1599 trames de 155 octets, checksums valides à 100 %, contenu identique
octet par octet sur deux dumps indépendants.

Structure d'une trame de bulk dump :

    F0 41 00 00 00 00 14 12 <ctr> <ctr> <143 octets de données> <checksum> F7
    |-- en-tête ES-8 -------| |compteur| |--------- données -----------|

- `F0 41` : SysEx Roland.
- `00 00 00 00 14` : identification (répartition device/model ID exacte
  non confirmée ; le format Roland classique GS n'en a que deux).
- `12` : DT1 (écriture de données).
- Compteur sur 2 octets (base 128), +1 par trame, de 00 10 à 12 4E sur
  un dump complet. Le dump entier est reproductible octet par octet.
- Le checksum Roland couvre tout ce qui suit l'en-tête (octet 8 → F7-2).

Organisation d'un dump complet (dumps différentiels du 2026-10-17) :

- compteurs 0–15 : bloc système (16 trames) ;
- compteurs 16+2k et 17+2k : patch k (0-indexé, 1-1 = k 0, 100-8 = k 799).
  Un dump observé s'arrête au compteur 1614 : le patch 100-8 n'y a que sa
  première trame (question ouverte).

Encodage d'un patch : les 286 octets MIDI sont des groupes de 8 octets,
un octet porteur suivi de 7 octets de données ; le bit 6 du porteur est
le bit 7 du premier octet de données, le bit 5 celui du second, etc. Le
dernier groupe est partiel (porteur + 5). On obtient 250 octets de
données 8 bits, lus comme un flux de bits MSB d'abord. Le nom (16
caractères ASCII de 7 bits) commence au bit 195.
"""

from __future__ import annotations

from dataclasses import dataclass

from .roland import (
    CMD_DT1,
    SYSEX_END,
    SYSEX_START,
    ChecksumError,
    CodecError,
    NotRolandSysex,
    checksum,
)

# F0 41 00 00 00 00 14 12 : constructeur Roland + identification ES-8 + DT1.
ES8_BULK_HEADER = bytes(
    [SYSEX_START, 0x41, 0x00, 0x00, 0x00, 0x00, 0x14, CMD_DT1]
)
HEADER_LEN = len(ES8_BULK_HEADER)
BULK_DATA_LEN = 143
BULK_FRAME_LEN = HEADER_LEN + 2 + BULK_DATA_LEN + 2  # en-tête + compteur + données + checksum + F7

PATCH_FRAMES = 2
PATCH_RECORD_LEN = PATCH_FRAMES * BULK_DATA_LEN
PATCH_COUNT = 800
PATCHES_PER_BANK = 8

GROUP_LEN = 8  # 1 octet porteur + 7 octets de données
PATCH_DATA_LEN = 250  # 35 groupes complets × 7 + groupe final de 5

PATCH_NAME_BIT = 195
PATCH_NAME_LEN = 16
PATCH_NAME_CHAR_BITS = 7

# Compteurs d'un dump complet (empiriques, reproductibles).
SYSTEM_FIRST_COUNTER = 0
SYSTEM_FRAMES = 16
PATCH_FIRST_COUNTER = SYSTEM_FIRST_COUNTER + SYSTEM_FRAMES
BULK_LAST_COUNTER = 1614


@dataclass(frozen=True)
class ES8BulkMessage:
    """Une trame du bulk dump ES-8. `raw` conserve la trame d'origine."""

    counter: int
    data: bytes
    checksum: int
    raw: bytes

    @property
    def checksum_valid(self) -> bool:
        payload = self.raw[HEADER_LEN:-2]
        return self.checksum == checksum(payload)


def parse_es8_bulk_frame(frame: bytes) -> ES8BulkMessage:
    """Décode une trame de bulk dump ES-8.

    Lève NotRolandSysex si la trame ne correspond pas au format ES-8,
    ChecksumError si le checksum est faux. Aucun rejet silencieux.
    """
    if len(frame) < HEADER_LEN + 3:
        raise NotRolandSysex(f"Trame trop courte ({len(frame)} octets) pour une trame ES-8.")
    if frame[0] != SYSEX_START or frame[-1] != SYSEX_END:
        raise NotRolandSysex("La trame ne commence pas par F0 ou ne finit pas par F7.")
    if bytes(frame[:HEADER_LEN]) != ES8_BULK_HEADER:
        raise NotRolandSysex(
            f"En-tête ES-8 attendu {ES8_BULK_HEADER.hex(' ')}, lu {bytes(frame[:HEADER_LEN]).hex(' ')}."
        )
    if any(b >= 0x80 for b in frame[HEADER_LEN:-1]):
        raise NotRolandSysex("Octet >= 0x80 dans le corps de la trame.")

    payload = frame[HEADER_LEN:-2]
    expected = frame[-2]
    if checksum(payload) != expected:
        raise ChecksumError(
            f"Checksum invalide : lu {expected:#04x}, calculé {checksum(payload):#04x}."
        )

    counter = frame[HEADER_LEN] * 128 + frame[HEADER_LEN + 1]
    data = bytes(frame[HEADER_LEN + 2 : -2])

    return ES8BulkMessage(counter=counter, data=data, checksum=expected, raw=frame)


def build_es8_bulk_frame(counter: int, data: bytes) -> bytes:
    """Construit une trame de bulk dump ES-8 complète, checksum inclus."""
    if not 0 <= counter <= 0x3FFF:
        raise CodecError(f"Compteur hors plage 0-0x3FFF : {counter}.")
    if len(data) != BULK_DATA_LEN:
        raise CodecError(f"Les données font {len(data)} octets, {BULK_DATA_LEN} attendus.")
    ctr = bytes([counter // 128, counter % 128])
    payload = ctr + data
    return ES8_BULK_HEADER + payload + bytes([checksum(payload), SYSEX_END])


def is_es8_bulk_frame(frame: bytes) -> bool:
    """True si la trame porte l'en-tête de bulk dump ES-8."""
    return len(frame) >= HEADER_LEN and bytes(frame[:HEADER_LEN]) == ES8_BULK_HEADER


def frames_by_counter(frames: list[bytes]) -> dict[int, bytes]:
    """Indexe les données des trames de bulk dump par compteur.

    Lève CodecError sur un compteur en double : deux dumps mélangés dans
    un même fichier fausseraient silencieusement le découpage.
    """
    by_counter: dict[int, bytes] = {}
    for frame in frames:
        msg = parse_es8_bulk_frame(frame)
        if msg.counter in by_counter:
            raise CodecError(f"Compteur {msg.counter} présent deux fois.")
        by_counter[msg.counter] = msg.data
    return by_counter


@dataclass(frozen=True)
class BulkDump:
    """Dump découpé. Les données sont encore empaquetées (domaine MIDI 7 bits).

    `system` vaut None si une trame système manque. `patches` ne contient
    que les patchs dont les deux trames sont présentes ; `incomplete` liste
    les patchs dont une seule trame a été reçue.
    """

    system: bytes | None
    patches: dict[int, bytes]
    incomplete: list[int]


def split_dump(frames: list[bytes]) -> BulkDump:
    """Découpe un bulk dump en bloc système et enregistrements de patch, par compteur."""
    data = frames_by_counter(frames)
    sys_counters = range(SYSTEM_FIRST_COUNTER, SYSTEM_FIRST_COUNTER + SYSTEM_FRAMES)
    system = (
        b"".join(data[c] for c in sys_counters)
        if all(c in data for c in sys_counters)
        else None
    )
    patches: dict[int, bytes] = {}
    incomplete: list[int] = []
    for index in range(PATCH_COUNT):
        first = PATCH_FIRST_COUNTER + index * PATCH_FRAMES
        halves = [data.get(first + i) for i in range(PATCH_FRAMES)]
        if all(h is not None for h in halves):
            patches[index] = b"".join(halves)
        elif any(h is not None for h in halves):
            incomplete.append(index)
    return BulkDump(system=system, patches=patches, incomplete=incomplete)


def unpack_7to8(packed: bytes) -> bytes:
    """Dépaquette des groupes (porteur + 7 données) en octets 8 bits.

    Lève CodecError si un porteur a des bits hors de ceux de son groupe :
    le re-empaquetage ne serait plus bit à bit identique.
    """
    out = bytearray()
    for start in range(0, len(packed), GROUP_LEN):
        carrier, *data = packed[start : start + GROUP_LEN]
        if not data:
            raise CodecError(f"Groupe sans données à l'octet {start}.")
        if carrier & ((1 << (7 - len(data))) - 1):
            raise CodecError(f"Bits parasites dans le porteur à l'octet {start}.")
        for i, byte in enumerate(data):
            out.append(byte | ((carrier >> (6 - i)) & 1) << 7)
    return bytes(out)


def pack_8to7(data: bytes) -> bytes:
    """Empaquette des octets 8 bits en groupes (porteur + 7 données). Inverse de unpack_7to8."""
    out = bytearray()
    for start in range(0, len(data), GROUP_LEN - 1):
        chunk = data[start : start + GROUP_LEN - 1]
        carrier = 0
        for i, byte in enumerate(chunk):
            carrier |= (byte >> 7) << (6 - i)
        out.append(carrier)
        out.extend(byte & 0x7F for byte in chunk)
    return bytes(out)


def get_bits(data: bytes, offset: int, width: int) -> int:
    """Lit `width` bits à partir du bit `offset` (flux MSB d'abord)."""
    value = 0
    for pos in range(offset, offset + width):
        value = value << 1 | (data[pos // 8] >> (7 - pos % 8)) & 1
    return value


def set_bits(data: bytes, offset: int, width: int, value: int) -> bytes:
    """Écrit `value` sur `width` bits à partir du bit `offset` ; rend une copie."""
    if not 0 <= value < 1 << width:
        raise CodecError(f"Valeur {value} hors plage pour {width} bits.")
    out = bytearray(data)
    for i, pos in enumerate(range(offset, offset + width)):
        bit = value >> (width - 1 - i) & 1
        mask = 1 << (7 - pos % 8)
        out[pos // 8] = out[pos // 8] | mask if bit else out[pos // 8] & ~mask
    return bytes(out)


def patch_name(data: bytes) -> str:
    """Nom d'un patch, depuis ses données dépaquetées (250 octets)."""
    return "".join(
        chr(get_bits(data, PATCH_NAME_BIT + i * PATCH_NAME_CHAR_BITS, PATCH_NAME_CHAR_BITS))
        for i in range(PATCH_NAME_LEN)
    )


def patch_label(index: int) -> str:
    """Numéro de patch tel qu'affiché par l'ES-8 : banque-numéro (1-1 … 100-8)."""
    bank, number = divmod(index, PATCHES_PER_BANK)
    return f"{bank + 1}-{number + 1}"
