"""Tests du format de bulk dump ES-8 sur la fixture réelle.

Fixture : tests/fixtures/es8_bulk_session1.syx — premier dump complet de
l'ES-8 (1599 trames, checksums 100 % valides, reproductible octet par
octet sur deux captures indépendantes).
"""

from pathlib import Path

import pytest

from es8ctl.codec import (
    BULK_DATA_LEN,
    BULK_LAST_COUNTER,
    PATCH_FIRST_COUNTER,
    ChecksumError,
    CodecError,
    NotRolandSysex,
    build_es8_bulk_frame,
    is_es8_bulk_frame,
    parse_es8_bulk_frame,
    split_frames,
)

FIXTURE = Path(__file__).parent / "fixtures" / "es8_bulk_session1.syx"


@pytest.fixture(scope="module")
def frames():
    return list(split_frames(FIXTURE.read_bytes()))


def test_fixture_exists_and_has_expected_frames(frames):
    assert FIXTURE.exists()
    assert len(frames) == 1599
    assert all(len(f) == 155 for f in frames)


def test_all_frames_are_es8_bulk(frames):
    assert all(is_es8_bulk_frame(f) for f in frames)


def test_all_checksums_valid(frames):
    msgs = [parse_es8_bulk_frame(f) for f in frames]
    assert all(m.checksum_valid for m in msgs)


def test_counter_sequence_complete_no_gaps(frames):
    # Cette capture a manqué le bloc système (compteurs 0-15) : elle
    # commence au premier patch.
    counters = [parse_es8_bulk_frame(f).counter for f in frames]
    assert counters[0] == PATCH_FIRST_COUNTER
    assert counters[-1] == BULK_LAST_COUNTER - 1  # capture arrêtée avant 0C 4F
    assert all(b - a == 1 for a, b in zip(counters, counters[1:]))


def test_data_payload_is_140_bytes(frames):
    msgs = [parse_es8_bulk_frame(f) for f in frames]
    assert all(len(m.data) == BULK_DATA_LEN for m in msgs)


def test_roundtrip_bit_identical(frames):
    """Le critère de sortie de l'étape 1 du plan : dump décodé puis
    re-encodé = octet pour octet le dump d'origine."""
    for frame in frames:
        msg = parse_es8_bulk_frame(frame)
        assert build_es8_bulk_frame(msg.counter, msg.data) == frame


def test_build_rejects_wrong_data_size():
    with pytest.raises(CodecError):
        build_es8_bulk_frame(16, b"\x00" * 139)
    with pytest.raises(CodecError):
        build_es8_bulk_frame(16, b"\x00" * 141)


def test_parse_rejects_bad_checksum():
    frame = build_es8_bulk_frame(16, b"\x00" * BULK_DATA_LEN)
    bad = frame[:-2] + bytes([(frame[-2] + 1) % 128, frame[-1]])
    with pytest.raises(ChecksumError):
        parse_es8_bulk_frame(bad)


def test_parse_rejects_wrong_header():
    frame = bytearray(build_es8_bulk_frame(16, b"\x00" * BULK_DATA_LEN))
    frame[6] = 0x15  # octet d'identification altéré
    with pytest.raises(NotRolandSysex):
        parse_es8_bulk_frame(bytes(frame))
