"""Tests du découpage, de l'empaquetage 8→7, des noms et du diff, sur fixtures réelles.

- session1 : dump sans bloc système (compteurs 16-1614), patchs de l'utilisateur.
- session2_name_A : dump complet (compteurs 0-1614), identique à session1
  sauf le nom du patch 0-1 (le premier) renommé « AAAAAAAAAAAAAAAA » au panneau.
"""

from pathlib import Path

import pytest

from es8ctl.capture import inspect_file
from es8core.codec import (
    BULK_DATA_LEN,
    PATCH_DATA_LEN,
    CodecError,
    build_es8_bulk_frame,
    frames_by_counter,
    get_bits,
    pack_8to7,
    pack_page,
    patch_label,
    patch_name,
    set_bits,
    unpack_7to8,
    unpack_page,
)
from es8core.codec.es8 import PATCH_NAME_BIT, PATCH_NAME_CHAR_BITS, PATCH_NAME_LEN
from es8core.diff import diff_files, load_dump

FIXTURES = Path(__file__).parent / "fixtures"
SESSION1 = FIXTURES / "es8_bulk_session1.syx"
NAME_A = FIXTURES / "es8_bulk_session2_name_A.syx"


@pytest.fixture(scope="module")
def dump1():
    return load_dump(SESSION1)


@pytest.fixture(scope="module")
def dump2():
    return load_dump(NAME_A)


def test_split_without_system_block(dump1):
    assert dump1.system is None
    assert len(dump1.patches) == 799
    assert dump1.incomplete == [799]  # 99-8 : seule la première trame est reçue


def test_split_with_system_block(dump2):
    assert dump2.system is not None
    assert len(dump2.system) == 16 * BULK_DATA_LEN
    assert len(dump2.patches) == 799


def test_unpack_pack_roundtrip_all_patches(dump1, dump2):
    for dump in (dump1, dump2):
        for record in dump.patches.values():
            data = unpack_page(record)
            assert len(data) == PATCH_DATA_LEN
            assert pack_page(data) == record


def test_unpack_rejects_stray_carrier_bits():
    with pytest.raises(CodecError):
        unpack_7to8(bytes([0x01, 0, 0, 0, 0, 0]))  # porteur de 5 données : bits 0-1 réservés


def test_pack_8to7_roundtrip_message():
    data = bytes(range(0, 250, 2))  # 125 octets, bits de poids fort variés
    packed = pack_8to7(data)
    assert len(packed) == BULK_DATA_LEN
    assert unpack_7to8(packed) == data


def test_page_is_two_independently_packed_messages(dump2):
    """Spec Roland : chaque message de 125 octets est encodé séparément."""
    record = dump2.system[BULK_DATA_LEN * 2 : BULK_DATA_LEN * 4]  # page système 2
    data = unpack_page(record)
    assert data[:125] == unpack_7to8(record[:BULK_DATA_LEN])
    assert data[125:] == unpack_7to8(record[BULK_DATA_LEN:])


def test_patch_names(dump1, dump2):
    names = [patch_name(unpack_page(r)) for r in dump1.patches.values()]
    assert names.count("BOSS ES-8       ") == 751
    assert patch_name(unpack_page(dump1.patches[7])) == "TEMPLATE        "
    assert patch_name(unpack_page(dump2.patches[0])) == "AAAAAAAAAAAAAAAA"


def test_bits_roundtrip():
    data = bytes(4)
    data = set_bits(data, 5, 7, 0x41)
    assert get_bits(data, 5, 7) == 0x41
    assert data == bytes([0b00000100, 0b00010000, 0, 0])
    with pytest.raises(CodecError):
        set_bits(data, 0, 3, 8)


def test_frames_by_counter_rejects_duplicates():
    frame = build_es8_bulk_frame(16, b"\x00" * BULK_DATA_LEN)
    with pytest.raises(CodecError):
        frames_by_counter([frame, frame])


def test_patch_label():
    # Banques numérotées à partir de 0, comme sur l'écran de l'ES-8.
    assert patch_label(0) == "0-1"
    assert patch_label(7) == "0-8"
    assert patch_label(8) == "1-1"
    assert patch_label(392) == "49-1"
    assert patch_label(799) == "99-8"


def test_diff_identical_fixture_is_empty():
    result = diff_files(SESSION1, SESSION1)
    assert result["changed"] is False
    assert result["patches"] == []


def test_diff_rename_touches_only_name_bits():
    """Expérience différentielle n°1 : renommer 0-1 ne change que les bits du nom."""
    result = diff_files(SESSION1, NAME_A)
    assert result["system"]["compared"] is False  # session1 n'a pas de bloc système
    assert [p["patch"] for p in result["patches"]] == ["0-1"]
    patch = result["patches"][0]
    assert patch["name"] == {"old": "BOSS ES-8       ", "new": "AAAAAAAAAAAAAAAA"}
    name_end = PATCH_NAME_BIT + PATCH_NAME_LEN * PATCH_NAME_CHAR_BITS
    for run in patch["bit_runs"]:
        assert PATCH_NAME_BIT <= run["bit"] and run["bit"] + run["width"] <= name_end


def test_diff_reports_coverage_as_label_ranges():
    result = diff_files(NAME_A, SESSION1)
    assert result["coverage"]["incomplete"] == {"a": ["99-8"], "b": ["99-8"]}
    assert result["coverage"]["only_in_a"] == []


def test_inspect_reports_no_errors_on_fixtures():
    for path in (SESSION1, NAME_A):
        result = inspect_file(path)
        assert result["decode_errors"] == []
        assert all(f["decoded"]["format"] == "es8-bulk" for f in result["frames"])
