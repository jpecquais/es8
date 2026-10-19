"""Tests du bloc système (firmware v2), sur la fixture complète."""

from pathlib import Path

import pytest

from es8core.codec import CodecError
from es8core.diff import load_dump
from es8core.system import (
    PAGE_FIELDS,
    decode_system,
    encode_system,
    split_pages,
    system_out_of_range,
)

FIXTURE = Path(__file__).parent / "fixtures" / "es8_bulk_session2_name_A.syx"


@pytest.fixture(scope="module")
def system():
    return load_dump(FIXTURE).system


def test_page1_layout_anchors():
    """Spec v1 : bits 0-84 ; extension v2 jusqu'au bit 306 (base de l'éditeur officiel)."""
    by_name = {f.name: f for f in PAGE_FIELDS[0]}
    assert by_name["others_lcd_contrast"].bit == 9 * 8 + 0
    assert by_name["memory_manual"].bit == 10 * 8 + 4
    assert by_name["ctl_sw"].bit == 85
    assert by_name["manual_number1"].bit == 271
    assert by_name["tempo_hold"].bit == 303 and by_name["link"].bit == 304
    assert PAGE_FIELDS[0][-1].end == 306


def test_unmapped_page1_bits_are_zero_on_fixture(system):
    page1 = split_pages(system)[0]
    assert int.from_bytes(page1, "big") & ((1 << (2000 - 306)) - 1) == 0


def test_decode_matches_editor_defaults(system):
    s = decode_system(system)
    assert system_out_of_range(s) == []
    assert s["play_option_bank_extent_max"] == 99
    assert s["others_lcd_contrast"] == 4
    assert s["ctl_sw"] == [0, 1] + [0] * 14
    assert s["ctl_func"] == [1, 2, 3, 4, *range(7, 19)]


def test_pc_maps_are_identity(system):
    """Tables de program change par défaut : PC n de la banque b → patch 128·b + n (≤ 799)."""
    s = decode_system(system)
    for bank in range(7):
        assert s[f"pc_map_bank{bank}_pc"] == [min(128 * bank + i, 799) for i in range(128)]


def test_roundtrip_and_targeted_edit(system):
    s = decode_system(system)
    assert encode_system(system, s) == system
    edited = decode_system(encode_system(system, {"others_lcd_contrast": 7}))
    assert edited["others_lcd_contrast"] == 7
    assert {k: v for k, v in edited.items() if k != "others_lcd_contrast"} == {
        k: v for k, v in s.items() if k != "others_lcd_contrast"
    }


@pytest.mark.parametrize(
    "values",
    [{"unknown": 1}, {"others_lcd_contrast": 10}, {"pc_map_bank0_pc": [0] * 127}],
)
def test_encode_rejects_invalid_input(system, values):
    with pytest.raises(CodecError):
        encode_system(system, values)
