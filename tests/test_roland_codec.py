"""Tests du codec Roland, sans matériel.

Trame de référence : "GS Reset" (exemple documenté du format Roland,
adresse sur 3 octets) :
    F0 41 10 42 12 40 00 7F 00 41 F7
checksum = 128 - (0x40 + 0x00 + 0x7F + 0x00) mod 128 = 0x41
"""

import pytest

from es8core.codec import (
    CMD_DT1,
    CMD_RQ1,
    ChecksumError,
    CodecError,
    NotRolandSysex,
    build_frame,
    checksum,
    parse_frame,
    parse_stream,
    split_frames,
)

GS_RESET = bytes.fromhex("F0 41 10 42 12 40 00 7F 00 41 F7")


def test_checksum_roland_reference():
    # Somme = 0x40 + 0x7F = 0xBF ; 128 - 0xBF = 0x41
    assert checksum([0x40, 0x00, 0x7F, 0x00]) == 0x41


def test_checksum_zero_and_max():
    assert checksum([0x00, 0x00, 0x00, 0x00]) == 0x00
    assert checksum([0x7F, 0x7F, 0x7F, 0x7F]) == 0x04


def test_parse_gs_reset_address_3_bytes():
    msg = parse_frame(GS_RESET, address_size=3)
    assert msg.device_id == 0x10
    assert msg.model_id == 0x42
    assert msg.command == CMD_DT1
    assert msg.is_dt1 and not msg.is_rq1
    assert msg.address == (0x40, 0x00, 0x7F)
    assert msg.data == b"\x00"
    assert msg.checksum_valid


def test_parse_then_build_roundtrip():
    frame = build_frame(0x10, 0x5A, CMD_RQ1, [0x20, 0x00, 0x00, 0x00], [0x10, 0x00])
    assert frame[0] == 0xF0 and frame[-1] == 0xF7
    msg = parse_frame(frame, address_size=4)
    assert msg.is_rq1
    assert msg.address == (0x20, 0x00, 0x00, 0x00)
    assert msg.data == b"\x10\x00"
    # Re-encodage bit à bit identique
    assert build_frame(msg.device_id, msg.model_id, msg.command, msg.address, msg.data) == frame


def test_invalid_checksum_raises():
    bad = GS_RESET[:-2] + bytes([0x42]) + bytes([0xF7])
    with pytest.raises(ChecksumError):
        parse_frame(bad, address_size=3)


def test_non_roland_manufacturer_raises():
    alien = bytes.fromhex("F0 42 10 42 12 40 00 7F 00 41 F7")
    with pytest.raises(NotRolandSysex):
        parse_frame(alien, address_size=3)


def test_high_byte_in_body_raises():
    bad = bytes.fromhex("F0 41 10 42 12 40 80 7F 00 41 F7")
    with pytest.raises(NotRolandSysex):
        parse_frame(bad, address_size=3)


def test_short_frame_raises():
    with pytest.raises(NotRolandSysex):
        parse_frame(bytes.fromhex("F0 41 10 F7"), address_size=3)


def test_out_of_range_byte_in_build_rejected():
    with pytest.raises(CodecError):
        build_frame(0x10, 0x42, CMD_DT1, [0x80], [])


def test_split_frames_ignores_stray_bytes():
    stream = b"\xf8" + GS_RESET + b"\xfe\x90" + bytes.fromhex(
        "F0 41 10 42 12 40 00 7F 00 41 F7"
    )
    frames = list(split_frames(stream))
    assert len(frames) == 2
    assert frames[0] == GS_RESET


def test_split_frames_rejects_nested_f0():
    stream = bytes([0xF0, 0x41, 0x10, 0xF0])
    with pytest.raises(NotRolandSysex):
        list(split_frames(stream))


def test_parse_stream_reports_errors_explicitly():
    stream = GS_RESET + GS_RESET[:-2] + bytes([0x00, 0xF7])
    results = list(parse_stream(stream, address_size=3))
    assert len(results) == 2
    ok_frame, ok_msg, ok_err = results[0]
    assert ok_msg is not None and ok_err is None and ok_msg.checksum_valid
    bad_frame, bad_msg, bad_err = results[1]
    assert bad_msg is None and bad_err is not None


def test_single_data_byte_frame_roundtrip():
    frame = build_frame(0x10, 0x5A, CMD_DT1, [0x7F, 0x00, 0x00, 0x00], [0x00])
    msg = parse_frame(frame, address_size=4)
    assert msg.data == b"\x00"
    assert msg.checksum_valid
