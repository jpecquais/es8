"""Tests de la carte des champs de patch, sur fixtures réelles."""

from pathlib import Path

import pytest

from es8ctl.codec import CodecError, parse_patch_label, patch_label, unpack_7to8
from es8ctl.diff import load_dump
from es8ctl.patch import LOOP_NAMES, PATCH_FIELDS, decode_patch, encode_patch

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def dump1():
    return load_dump(FIXTURES / "es8_bulk_session1.syx")


def data(dump, label):
    return unpack_7to8(dump.patches[parse_patch_label(label)])


def test_fields_do_not_overlap():
    spans = sorted((f.bit, f.end) for f in PATCH_FIELDS)
    assert all(end <= nxt for (_, end), (nxt, _) in zip(spans, spans[1:]))


def test_decode_user_patch(dump1):
    patch = decode_patch(data(dump1, "1-8"))
    assert patch["name"] == "TEMPLATE        "
    assert patch["master_bpm"] == 76
    assert [loop for loop in LOOP_NAMES if patch["loop_sw"][loop]] == ["L4", "L6", "LV"]
    assert patch["loop_position"][:9] == [0, 8, 7, 4, 6, 5, 3, 2, 1]


def test_loop_position_shape_on_all_patches(dump1):
    """Sur les 799 patchs : 0-9 une fois chacun, 10-15 deux fois chacun.

    0-9 = les loops (dont 9 en fin de chaîne), 10-15 = marqueurs appariés,
    intercalés librement (ex. TOC-FAT) : probablement les branches
    série/parallèle. Leur sens exact reste à établir.
    """
    expected = sorted([*range(10), *range(10, 16), *range(10, 16)])
    for record in dump1.patches.values():
        assert sorted(decode_patch(unpack_7to8(record))["loop_position"]) == expected


def test_encode_decode_roundtrip_all_patches(dump1):
    for record in dump1.patches.values():
        original = unpack_7to8(record)
        assert encode_patch(original, decode_patch(original)) == original


def test_encode_changes_only_target_field(dump1):
    original = data(dump1, "1-1")
    edited = encode_patch(original, {"master_bpm": 107, "name": "MY PATCH        "})
    decoded = decode_patch(edited)
    assert decoded["master_bpm"] == 107
    assert decoded["name"] == "MY PATCH        "
    assert decoded["loop_sw"] == decode_patch(original)["loop_sw"]


@pytest.mark.parametrize(
    "fields",
    [
        {"unknown": 1},
        {"master_bpm": 512},  # 9 bits
        {"master_bpm": True},
        {"name": "TROP COURT"},
        {"name": "ACCENTUÉ        "},
        {"loop_sw": {"L1": True}},
        {"loop_position": [0] * 21},
    ],
)
def test_encode_rejects_invalid_input(dump1, fields):
    with pytest.raises(CodecError):
        encode_patch(data(dump1, "1-1"), fields)


def test_parse_patch_label_roundtrip():
    assert all(parse_patch_label(patch_label(i)) == i for i in range(800))
    for bad in ("0-1", "101-1", "1-9", "1", "a-b"):
        with pytest.raises(CodecError):
            parse_patch_label(bad)
