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

# Compteur d'un dump complet, bornes incluses (empirique, reproductible).
BULK_FIRST_COUNTER = 16
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
