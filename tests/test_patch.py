"""Tests de la carte des champs de patch (firmware v2), sur fixtures réelles."""

import json
from pathlib import Path

import pytest

from es8ctl.codec import CodecError, parse_patch_label, patch_label, unpack_page
from es8ctl.diff import load_dump
from es8ctl.patch import (
    FIELDS_BY_NAME,
    PATCH_BITS_USED,
    PATCH_FIELDS,
    decode_patch,
    encode_patch,
    out_of_range,
)

FIXTURES = Path(__file__).parent / "fixtures"
ORACLE_DEFAULTS = {
    # Valeurs du patch d'usine telles que l'éditeur officiel les exporte (.bel v2).
    "exp1": 128,
    "exp2": 129,
    "master_bpm": 120,
    "exp_max": [127, 127],
    "ctl_max": [1] * 16,
}


@pytest.fixture(scope="module")
def dump1():
    return load_dump(FIXTURES / "es8_bulk_session1.syx")


@pytest.fixture(scope="module")
def all_patches(dump1):
    dump2 = load_dump(FIXTURES / "es8_bulk_session2_name_A.syx")
    return [unpack_page(r) for d in (dump1, dump2) for r in d.patches.values()]


def data(dump, label):
    return unpack_page(dump.patches[parse_patch_label(label)])


def test_layout_is_contiguous_and_fits_page():
    assert all(a.end == b.bit for a, b in zip(PATCH_FIELDS, PATCH_FIELDS[1:]))
    assert PATCH_BITS_USED == 1998


def test_layout_anchors():
    """Ancres : dumps différentiels (bits absolus) et spec v1 décalée de 27 bits."""
    assert FIELDS_BY_NAME["loop_sw"].bit == 0
    assert FIELDS_BY_NAME["master_bpm"].bit == 186
    assert FIELDS_BY_NAME["name"].bit == 195
    v1_to_v2 = {"carry_over_loop": 73, "ctl1": 89, "midi_tx_ch": 290, "ctl_func": 762,
                "assign_sw": 930, "assign_wave_pedal_form": 1938}
    for name, v1_bit in v1_to_v2.items():
        assert FIELDS_BY_NAME[name].bit == v1_bit + 27


def test_padding_bits_are_zero(all_patches):
    for data_ in all_patches:
        assert data_[-1] & 0b11 == 0


def test_all_values_in_range(all_patches):
    for data_ in all_patches:
        assert out_of_range(decode_patch(data_)) == []


def test_factory_patch_matches_editor_defaults(dump1):
    records = list(dump1.patches.values())
    factory = decode_patch(unpack_page(max(set(records), key=records.count)))
    assert factory["name"] == "BOSS ES-8       "
    for name, value in ORACLE_DEFAULTS.items():
        assert factory[name] == value, name
    # Seconde moitié de page (octets 125+) : défauts uniformes sur les 12 assigns.
    # Un dépaquetage de la page d'un seul tenant y produisait des valeurs disparates.
    assert factory["assign_target_cc_no"] == [80] * 12
    assert factory["assign_int_pedal_time"] == [30] * 12
    assert factory["assign_wave_pedal_rate"] == [7] * 12
    assert factory["assign_wave_pedal_form"] == [2] * 12


def test_decode_user_patch(dump1):
    patch = decode_patch(data(dump1, "1-8"))
    assert patch["name"] == "TEMPLATE        "
    assert patch["master_bpm"] == 76
    assert patch["loop_sw"] == [0, 0, 0, 1, 0, 1, 0, 0, 1]
    assert patch["loop_position"][:9] == [0, 8, 7, 4, 6, 5, 3, 2, 1]


def test_decoded_patch_is_json_serializable(dump1):
    json.dumps(decode_patch(data(dump1, "1-1")))


def test_loop_position_shape(all_patches):
    """0-9 une fois chacun, 10-15 deux fois chacun (marqueurs appariés)."""
    expected = sorted([*range(10), *range(10, 16), *range(10, 16)])
    for data_ in all_patches:
        assert sorted(decode_patch(data_)["loop_position"]) == expected


def test_encode_decode_roundtrip_all_patches(all_patches):
    for data_ in all_patches:
        assert encode_patch(data_, decode_patch(data_)) == data_


def test_encode_changes_only_target_fields(dump1):
    original = data(dump1, "1-1")
    edited = encode_patch(original, {"master_bpm": 107, "name": "MY PATCH        "})
    before, after = decode_patch(original), decode_patch(edited)
    assert after["master_bpm"] == 107
    assert after["name"] == "MY PATCH        "
    assert {k: v for k, v in after.items() if k not in ("master_bpm", "name")} == {
        k: v for k, v in before.items() if k not in ("master_bpm", "name")
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"unknown": 1},
        {"master_bpm": 19},  # min 20
        {"master_bpm": 501},
        {"master_bpm": True},
        {"name": "TROP COURT"},
        {"name": "ACCENTUÉ        "},
        {"loop_sw": [1] * 8},
        {"loop_sw": [2] * 9},
        {"ctl_func": [22] * 16},
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
