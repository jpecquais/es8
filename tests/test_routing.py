"""Tests de la chaîne de loops (loop_position ↔ notation écran) et des variantes."""

from pathlib import Path

import pytest

from es8core.apply import plan_changes
from es8core.codec import CodecError, parse_patch_label, split_frames, unpack_page
from es8core.diff import load_dump
from es8core.patch import decode_patch
from es8core.routing import parse, render, swap_loops, with_chain
from es8core.transform import op_variants

FIXTURE = Path(__file__).parent / "fixtures" / "es8_bulk_session2_name_A.syx"
FACTORY = [8, 7, 6, 5, 4, 3, 2, 1, 0, 9, 10, 11, 12, 10, 11, 12, 13, 14, 15, 13, 14, 15]
TOC_FAT = [0, 8, 7, 4, 6, 10, 5, 11, 3, 12, 2, 1, 9, 10, 11, 12, 13, 14, 15, 13, 14, 15]


@pytest.fixture(scope="module")
def dump():
    return load_dump(FIXTURE)


def positions(dump, label):
    return decode_patch(unpack_page(dump.patches[parse_patch_label(label)]))["loop_position"]


def test_render_matches_device_display(dump):
    """Lu sur l'écran de l'ES-8 : 0-3 « 87654321V », 0-8 « V87465321 », 6-2 « V8746(3//5)21 »."""
    assert render(positions(dump, "0-3")) == "87654321V"
    assert render(positions(dump, "0-8")) == "V87465321"
    assert render(positions(dump, "6-2")) == "V8746(3//5)21"


def test_render_parse_roundtrip_on_all_patches(dump):
    for record in dump.patches.values():
        pos = decode_patch(unpack_page(record))["loop_position"]
        assert parse(render(pos), base=pos) == pos


def test_parse_without_base_is_canonical():
    assert parse("87654321V") == FACTORY
    assert parse("V8746(3//5)21") == TOC_FAT
    assert render(parse("V8(3//)7654 21")) == "V8(3//)765421"


@pytest.mark.parametrize(
    "text",
    ["V8765432", "V876543211", "V8746(3/5)21", "V8746(3//5 21", "V87X654321",
     "V(1//2)(3//4)(5//6)87"],  # 3 parallèles du jeu « ( » : deux au plus
)
def test_parse_rejects(text):
    with pytest.raises(CodecError):
        parse(text)


def test_with_chain_keeps_spare_order():
    base = [0, 8, 7, 6, 5, 4, 3, 2, 1, 9, 13, 14, 15, 10, 11, 12, 10, 11, 12, 13, 14, 15]
    rebuilt = with_chain(base, [0, 8, 7, 4, 6, 10, 5, 11, 3, 12, 2, 1])
    assert rebuilt[rebuilt.index(9) + 1 :] == [13, 14, 15, 10, 11, 12, 13, 14, 15]


def test_with_chain_frees_markers_of_removed_parallel():
    series = with_chain(TOC_FAT, [0, 8, 7, 4, 6, 5, 3, 2, 1])
    assert render(series) == "V87465321"
    assert series[series.index(9) + 1 :] == [10, 11, 12, 13, 14, 15, 13, 14, 15, 10, 11, 12]


def test_swap_loops_in_chain():
    assert render(swap_loops(TOC_FAT, 6, 7)) == "V8647(3//5)21"
    assert render(swap_loops(TOC_FAT, 0, 8)) == "8V746(3//5)21"


def test_apply_accepts_loop_chain(tmp_path):
    frames = list(split_frames(FIXTURE.read_bytes()))
    plan = plan_changes(frames, {"patches": {"0-8": {"loop_chain": "V8746(3//5)21"}}})
    out = tmp_path / "exp.syx"
    out.write_bytes(plan.expected)
    assert render(positions(load_dump(out), "0-8")) == "V8746(3//5)21"
    with pytest.raises(CodecError):
        plan_changes(frames, {"patches": {"0-8": {"loop_chain": "V87", "loop_position": FACTORY}}})


def test_variants(dump):
    """Cas d'usage 3 : 50 variantes du patch 0-8 aux routings tous différents."""
    changes = op_variants(dump, "0-8", "10-1", 50)
    assert list(changes["patches"]) == [f"{i // 8}-{i % 8 + 1}" for i in range(80, 130)]
    source = decode_patch(unpack_page(dump.patches[parse_patch_label("0-8")]))
    chains = set()
    for n, (label, fields) in enumerate(changes["patches"].items(), start=1):
        current = decode_patch(unpack_page(dump.patches[parse_patch_label(label)]))
        variant = {**current, **fields}
        assert variant["name"] == f"TEMPLATE {n:02d}".ljust(16)
        pos = variant["loop_position"]
        assert sorted(pos) == sorted(source["loop_position"])
        assert pos[0] == 0  # V reste en tête
        assert pos != source["loop_position"]
        chains.add(tuple(pos))
        for key in ("loop_sw", "master_bpm", "assign_target", "ctl_func"):
            assert variant[key] == source[key]
    assert len(chains) == 50


def test_variants_deterministic_and_seeded(dump):
    assert op_variants(dump, "0-8", "10-1", 5) == op_variants(dump, "0-8", "10-1", 5)
    assert op_variants(dump, "0-8", "10-1", 5, seed=1) != op_variants(dump, "0-8", "10-1", 5)


def test_variants_keep_parallel_structure(dump):
    changes = op_variants(dump, "6-2", "20-1", 10)
    for fields in changes["patches"].values():
        text = render(fields["loop_position"])
        assert text.startswith("V") and "(" in text and "//" in text


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(source="0-8", into="0-1", count=3),  # 0-1 n'est pas vierge
        dict(source="0-8", into="0-7", count=2),  # contient la source
        dict(source="0-8", into="99-1", count=20),  # dépasse 99-8
        dict(source="0-8", into="10-1", count=0),
    ],
)
def test_variants_rejects(dump, kwargs):
    with pytest.raises(CodecError):
        op_variants(dump, **kwargs)


def test_hardware_constraints():
    from es8core.routing import mixers_used, problems

    none = [0] * 9
    assert problems(parse("V8746(3//5)21"), none) == []
    assert problems(parse("V8746(//5)321"), none) == []  # MIX avec une branche sèche
    assert mixers_used(parse("(1//2)(3//4)V5678"), none) == 2
    carry = [1, 0, 0, 0, 0, 0, 0, 0, 0]
    assert "mixers" in problems(parse("(1//2)(3//4)V5678"), carry)[0]  # 2 MIX + 1 carry-over
    assert mixers_used(parse("V87654321"), [0, 0, 0, 0, 0, 0, 1, 0, 0], stereo7=True) == 2  # L7 stéréo
    assert problems(parse("[1//2]V345678"), none) == []  # SEPARATE en début de chaîne
    assert "SEPARATE" in problems(parse("V[1//2]345678"), none)[0]
    assert problems(parse("8[1//2]V34567"), none, stereo8=True) == []  # après la loop 8 stéréo
    assert "contain" in problems(parse("V(1(2//3)//4)5678"), none)[0]


def test_plan_refuses_impossible_routing():
    import pytest

    from es8core.apply import plan_changes
    from es8core.codec import CodecError, split_frames

    frames = list(split_frames((Path(__file__).parent / "fixtures" / "es8_bulk_session2_name_A.syx").read_bytes()))
    with pytest.raises(CodecError, match="SEPARATE"):
        plan_changes(frames, {"patches": {"0-8": {"loop_chain": "V[1//2]345678"}}})
    plan_changes(frames, {"patches": {"0-8": {"loop_chain": "[1//2]V345678"}}})
