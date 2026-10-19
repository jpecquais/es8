"""Tests des transformations en masse, sur fixture réelle, chaînées avec apply."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from es8core.apply import plan_changes
from es8ctl.cli import app
from es8core.codec import CodecError, parse_patch_label, split_frames, unpack_page
from es8core.diff import load_dump
from es8core.patch import decode_patch
from es8core.transform import op_set, op_swap_loops, parse_assignment, select_patches

FIXTURE = Path(__file__).parent / "fixtures" / "es8_bulk_session2_name_A.syx"


@pytest.fixture(scope="module")
def dump():
    return load_dump(FIXTURE)


def decoded(dump, label):
    return decode_patch(unpack_page(dump.patches[parse_patch_label(label)]))


def test_parse_assignment_symbolic():
    assert parse_assignment("ctl_func[NUM_8]=BPM") == ("ctl_func", 11, 21)
    assert parse_assignment("loop_sw[L6] = 1") == ("loop_sw", 5, 1)
    assert parse_assignment("master_bpm=120") == ("master_bpm", None, 120)
    assert parse_assignment("name=MY PATCH") == ("name", None, "MY PATCH        ")
    with pytest.raises(CodecError):
        parse_assignment("name=" + "X" * 17)


@pytest.mark.parametrize(
    "text",
    ["nope=1", "master_bpm[0]=1", "ctl_func=1", "ctl_func[NUM_9]=BPM", "ctl_func[16]=0",
     "ctl_func[NUM_8]=TAPTEMPO", "garbage"],
)
def test_parse_assignment_rejects(text):
    with pytest.raises(CodecError):
        parse_assignment(text)


def test_select_patches(dump):
    assert select_patches(dump, "all") == sorted(dump.patches)
    assert select_patches(dump, "0-1..0-8") == list(range(8))
    assert select_patches(dump, "0-1,1-1..1-2") == [0, 8, 9]
    for bad in ("0-8..0-1", "99-8", "0-1..99-8"):  # 99-8 incomplet dans la fixture
        with pytest.raises(CodecError):
            select_patches(dump, bad)


def test_tap_tempo_on_all_patches(dump):
    """Cas d'usage 1 : footswitch 8 en tap tempo partout."""
    changes = op_set(dump, select_patches(dump, "all"), ["ctl_func[NUM_8]=BPM"])
    for label, fields in changes["patches"].items():
        assert set(fields) == {"ctl_func"}
        assert fields["ctl_func"][11] == 21
        before = decoded(dump, label)["ctl_func"]
        assert fields["ctl_func"][:11] == before[:11] and fields["ctl_func"][12:] == before[12:]
    # Les patchs déjà en tap tempo ne sont pas réécrits.
    untouched = set(dump.patches) - {parse_patch_label(k) for k in changes["patches"]}
    assert all(decoded(dump, f"{i // 8}-{i % 8 + 1}")["ctl_func"][11] == 21 for i in untouched)


def test_set_is_idempotent(dump, tmp_path):
    indices = select_patches(dump, "0-1..0-8")
    changes = op_set(dump, indices, ["master_bpm=133"])
    plan = plan_changes(list(split_frames(FIXTURE.read_bytes())), changes)
    after = tmp_path / "after.syx"
    after.write_bytes(plan.expected)
    assert op_set(load_dump(after), indices, ["master_bpm=133"]) == {"patches": {}}


def test_swap_loops_6_7(dump):
    """Cas d'usage 2 : échange des loops 6 et 7, y compris leur place dans la chaîne."""
    changes = op_swap_loops(dump, select_patches(dump, "all"), "6", "L7")
    assert changes["patches"]
    for label, fields in changes["patches"].items():
        before = decoded(dump, label)
        after = {**before, **fields}
        swap_chain = {6: 7, 7: 6}
        assert after["loop_position"] == [
            swap_chain.get(v, v) for v in before["loop_position"]
        ]
        for name in ("loop_sw", "carry_over_loop"):
            assert after[name][5] == before[name][6] and after[name][6] == before[name][5]
        swap = {5: 6, 6: 5}
        assert after["assign_target"] == [swap.get(v, v) for v in before["assign_target"]]


def test_swap_twice_is_identity(dump, tmp_path):
    indices = select_patches(dump, "all")
    plan = plan_changes(list(split_frames(FIXTURE.read_bytes())), op_swap_loops(dump, indices, "6", "7"))
    once = tmp_path / "once.syx"
    once.write_bytes(plan.expected)
    twice = plan_changes(list(split_frames(once.read_bytes())),
                         op_swap_loops(load_dump(once), indices, "6", "7"))
    assert twice.expected == FIXTURE.read_bytes()


def test_cli_transform_pipes_into_apply(tmp_path):
    runner = CliRunner()
    changes = tmp_path / "changes.json"
    result = runner.invoke(app, ["transform", "set", "ctl_func[NUM_8]=BPM", "-b", str(FIXTURE),
                                 "--patches", "0-1..0-8", "-o", str(changes)])
    assert result.exit_code == 0, result.output
    assert len(json.loads(changes.read_text())["patches"]) >= 1
    dry = runner.invoke(app, ["apply", str(changes), "-b", str(FIXTURE),
                              "--expected-out", str(tmp_path / "exp.syx")])
    assert dry.exit_code == 0, dry.output
    assert json.loads(dry.stdout)["mode"] == "dry-run"


def test_cli_transform_rejects_bad_assignment():
    result = CliRunner().invoke(app, ["transform", "set", "ctl_func[NUM_9]=BPM", "-b", str(FIXTURE)])
    assert result.exit_code == 2
