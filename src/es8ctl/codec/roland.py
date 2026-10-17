"""Codec pour l'enveloppe SysEx Roland.

Format général d'une trame Roland (DT1/RQ1) :

    F0 41 <device ID> <model ID> <command ID> <adresse N octets> <données M octets> <checksum> F7

- Constructeur : 0x41 (Roland).
- Commandes : DT1 (0x12, écriture de données) et RQ1 (0x11, requête).
- Checksum : 128 - (somme adresse+données mod 128), le tout mod 128.
- Taille d'adresse : 3 octets pour les appareils GS historiques,
  4 octets pour le matériel Roland/Boss récent. La valeur réelle pour
  l'ES-8 sera confirmée par le premier dump ; le brut est conservé dans
  chaque message pour pouvoir relire sans perte.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

SYSEX_START = 0xF0
SYSEX_END = 0xF7
ROLAND_MANUFACTURER_ID = 0x41

CMD_RQ1 = 0x11
CMD_DT1 = 0x12

DEFAULT_ADDRESS_SIZE = 4


class CodecError(Exception):
    """Erreur générique du codec, toujours explicite (jamais silencieuse."""


class NotRolandSysex(CodecError):
    """La trame n'est pas une trame SysEx Roland valide."""


class ChecksumError(CodecError):
    """Le checksum Roland de la trame ne correspond pas."""


def checksum(data: Iterable[int]) -> int:
    """Checksum Roland : complément à deux de la somme, modulo 128."""
    total = sum(data) % 128
    return (128 - total) % 128


@dataclass(frozen=True)
class RolandMessage:
    """Une trame Roland décodée. `raw` conserve la trame d'origine intacte."""

    device_id: int
    model_id: int
    command: int
    address: tuple[int, ...]
    data: bytes
    checksum: int
    raw: bytes

    @property
    def checksum_valid(self) -> bool:
        return self.checksum == checksum(tuple(self.address) + tuple(self.data))

    @property
    def is_rq1(self) -> bool:
        return self.command == CMD_RQ1

    @property
    def is_dt1(self) -> bool:
        return self.command == CMD_DT1


def split_frames(stream: bytes) -> Iterator[bytes]:
    """Extrait les trames F0..F7 d'un flux, en ignorant les octets hors trame."""
    frame: list[int] = []
    inside = False
    for byte in stream:
        if byte == SYSEX_START:
            if inside:
                raise NotRolandSysex("F0 imbriqué : trame SysEx incomplète avant le suivant.")
            inside = True
            frame = [byte]
        elif byte == SYSEX_END:
            if inside:
                frame.append(byte)
                yield bytes(frame)
                inside = False
        elif inside:
            if byte >= 0x80:
                raise NotRolandSysex(
                    f"Octet {byte:#04x} invalide dans une trame SysEx (attendu < 0x80)."
                )
            frame.append(byte)


def parse_frame(frame: bytes, address_size: int = DEFAULT_ADDRESS_SIZE) -> RolandMessage:
    """Décode une trame SysEx Roland.

    Lève NotRolandSysex si la trame est mal formée ou non Roland,
    ChecksumError si le checksum est faux. Aucun rejet silencieux.
    """
    if len(frame) < 10:
        raise NotRolandSysex(f"Trame trop courte ({len(frame)} octets) pour une trame Roland.")
    if frame[0] != SYSEX_START or frame[-1] != SYSEX_END:
        raise NotRolandSysex("La trame ne commence pas par F0 ou ne finit pas par F7.")
    if frame[1] != ROLAND_MANUFACTURER_ID:
        raise NotRolandSysex(
            f"ID constructeur {frame[1]:#04x} != Roland (0x41)."
        )
    if any(b >= 0x80 for b in frame[2:-1]):
        raise NotRolandSysex("Octet >= 0x80 dans le corps de la trame.")

    body = frame[2:-1]
    device_id, model_id, command = body[0], body[1], body[2]
    payload = body[3:-1]  # adresse + données, sans checksum
    expected = body[-1]

    if len(payload) < address_size + 1:
        raise NotRolandSysex(
            f"Corps trop court ({len(payload)} octets) pour une adresse de {address_size} octets."
        )

    address = tuple(payload[:address_size])
    data = bytes(payload[address_size:])

    if checksum(payload) != expected:
        raise ChecksumError(
            f"Checksum invalide : lu {expected:#04x}, calculé {checksum(payload):#04x}."
        )

    return RolandMessage(
        device_id=device_id,
        model_id=model_id,
        command=command,
        address=address,
        data=data,
        checksum=expected,
        raw=frame,
    )


def build_frame(
    device_id: int,
    model_id: int,
    command: int,
    address: Iterable[int],
    data: Iterable[int] = (),
) -> bytes:
    """Construit une trame Roland complète, checksum inclus."""
    address = tuple(address)
    data = tuple(data)
    for name, values in (("adresse", address), ("données", data)):
        for value in values:
            if not 0 <= value <= 0x7F:
                raise CodecError(f"Octet de {name} hors plage 0-0x7F : {value:#04x}.")
    payload = address + data
    return bytes(
        [
            SYSEX_START,
            ROLAND_MANUFACTURER_ID,
            device_id,
            model_id,
            command,
            *payload,
            checksum(payload),
            SYSEX_END,
        ]
    )


def parse_stream(
    stream: bytes,
    address_size: int = DEFAULT_ADDRESS_SIZE,
) -> Iterator[tuple[bytes, RolandMessage | None, str | None]]:
    """Décode un flux complet ; rend (trame brute, message ou None, erreur ou None).

    Toute trame invalide produit une erreur explicite plutôt qu'un rejet
    silencieux : le couple (message, erreur) permet de continuer l'analyse
    d'un dump partiel tout en signalant chaque problème.
    """
    for frame in split_frames(stream):
        try:
            yield frame, parse_frame(frame, address_size=address_size), None
        except CodecError as exc:
            yield frame, None, str(exc)
