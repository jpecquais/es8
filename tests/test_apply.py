"""Tests de l'écriture : plan, envoi (faux port MIDI), CLI apply/verify. Aucun matériel."""

import json
from pathlib import Path

import mido
import pytest
from typer.testing import CliRunner

from es8ctl import transfer
from es8ctl.apply import plan_changes
from es8ctl.cli import app
from es8ctl.codec import (
    CodecError,
    parse_es8_bulk_frame,
    split_frames,
    unpack_page,
)
from es8ctl.diff import load_dump
from es8ctl.patch import decode_patch
from es8ctl.system import decode_system

FIXTURES = Path(__file__).parent / "fixtures"
FULL = FIXTURES / "es8_bulk_session2_name_A.syx"  # avec bloc système
NO_SYSTEM = FIXTURES / "es8_bulk_session1.syx"
CHANGE = {"patches": {"49-1": {"name": "ES8CTL TEST     ", "master_bpm": 99}}}


def frames(path):
    return list(split_frames(path.read_bytes()))


frames_of = frames


def counters(fs):
    return [parse_es8_bulk_frame(f).counter for f in fs]


def test_plan_patch_change_emits_one_page():
    plan = plan_changes(frames(FULL), CHANGE)
    index = 49 * 8  # 49-1
    assert counters(plan.frames) == [16 + 2 * index, 17 + 2 * index]
    assert {(c["field"], c["new"]) for c in plan.changes} == {
        ("name", "ES8CTL TEST     "),
        ("master_bpm", 99),
    }


def test_plan_expected_dump_differs_only_on_target(tmp_path):
    plan = plan_changes(frames(FULL), CHANGE)
    expected, base = load_dump_bytes(tmp_path, plan.expected), load_dump(FULL)
    assert expected.system == base.system
    changed = [i for i in base.patches if expected.patches[i] != base.patches[i]]
    assert changed == [49 * 8]
    patch = decode_patch(unpack_page(expected.patches[49 * 8]))
    assert patch["name"] == "ES8CTL TEST     " and patch["master_bpm"] == 99


def load_dump_bytes(tmp_path, data):
    path = tmp_path / "expected.syx"
    path.write_bytes(data)
    return load_dump(path)


def test_plan_noop_change_emits_nothing():
    base = decode_patch(unpack_page(load_dump(FULL).patches[0]))
    plan = plan_changes(frames(FULL), {"patches": {"0-1": {"master_bpm": base["master_bpm"]}}})
    assert plan.frames == [] and plan.changes == []
    assert plan.expected == FULL.read_bytes()


def test_plan_system_change_emits_page1(tmp_path):
    plan = plan_changes(frames(FULL), {"system": {"others_lcd_contrast": 7}})
    assert counters(plan.frames) == [0, 1]
    assert decode_system(load_dump_bytes(tmp_path, plan.expected).system)["others_lcd_contrast"] == 7


@pytest.mark.parametrize(
    "base, changes",
    [
        (NO_SYSTEM, {"system": {"others_lcd_contrast": 7}}),  # pas de bloc système
        (FULL, {"patches": {"99-8": {"master_bpm": 100}}}),  # patch incomplet
        (FULL, {"patches": {"0-1": {"master_bpm": 9999}}}),  # hors bornes
        (FULL, {"patches": {"0-1": {"inconnu": 1}}}),
        (FULL, {"patchs": {}}),  # clé de premier niveau inconnue
        (FULL, {"patches": {"0-0": {}}}),
    ],
)
def test_plan_rejects_invalid(base, changes):
    with pytest.raises(CodecError):
        plan_changes(frames(base), changes)


class FakeOutput:
    def __init__(self, sent, fail_after=None):
        self.sent, self.fail_after = sent, fail_after

    def send(self, msg):
        if self.fail_after is not None and len(self.sent) == self.fail_after:
            raise KeyboardInterrupt
        self.sent.append(bytes([0xF0, *msg.data, 0xF7]))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def fake_midi(monkeypatch):
    sent = []
    state = {"fail_after": None}
    monkeypatch.setattr(transfer.time, "sleep", lambda s: None)
    monkeypatch.setattr(mido, "get_output_names", lambda: ["fake-out"])
    monkeypatch.setattr(
        mido, "open_output", lambda port: FakeOutput(sent, state["fail_after"])
    )
    return sent, state


def test_send_frames_in_order(fake_midi):
    sent, _ = fake_midi
    plan = plan_changes(frames(FULL), CHANGE)
    assert transfer.send_frames("fake-out", plan.frames) == 2
    assert sent == plan.frames


def test_send_rejects_interval_below_spec(fake_midi):
    with pytest.raises(ValueError):
        transfer.send_frames("fake-out", [], interval_s=0.01)
    with pytest.raises(ValueError):
        transfer.send_frames("fake-out", [], page_gap_s=0.01)


def test_send_paces_pages(monkeypatch, fake_midi):
    """Moitiés d'une page à `interval_s`, pause `page_gap_s` entre pages."""
    sleeps = []
    monkeypatch.setattr(transfer.time, "sleep", sleeps.append)
    frames = plan_changes(frames_of(FULL), {"patches": {"0-2": {"master_bpm": 90},
                                                        "0-3": {"master_bpm": 91},
                                                        "0-4": {"master_bpm": 92}}}).frames
    transfer.send_frames("fake-out", frames, interval_s=0.06, page_gap_s=0.8)
    assert sleeps == [0.06, 0.8, 0.06, 0.8, 0.06]


def test_send_rejects_odd_frame_count(fake_midi):
    with pytest.raises(ValueError):
        transfer.send_frames("fake-out", [b"\xf0\xf7"])


def run_apply(tmp_path, *extra):
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps(CHANGE))
    args = ["apply", str(changes), "-b", str(FULL), "--expected-out", str(tmp_path / "exp.syx"),
            "--backup-dir", str(tmp_path / "backups"), *extra]
    return CliRunner().invoke(app, args)


def test_cli_dry_run_sends_nothing(tmp_path, fake_midi):
    sent, _ = fake_midi
    result = run_apply(tmp_path)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["mode"] == "dry-run"
    assert sent == []
    assert not (tmp_path / "backups").exists()


def test_cli_write_backs_up_then_sends(tmp_path, fake_midi):
    sent, _ = fake_midi
    result = run_apply(tmp_path, "--write", "--port", "fake-out")
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["sent"] == 2 and len(sent) == 2
    assert Path(report["backup"]).read_bytes() == FULL.read_bytes()


def test_cli_write_requires_known_port(tmp_path, fake_midi):
    sent, _ = fake_midi
    assert run_apply(tmp_path, "--write").exit_code == 2
    assert run_apply(tmp_path, "--write", "--port", "nope").exit_code == 2
    assert sent == []


def test_cli_write_interrupted_reports_partial(tmp_path, fake_midi):
    sent, state = fake_midi
    state["fail_after"] = 1
    result = run_apply(tmp_path, "--write", "--port", "fake-out")
    assert result.exit_code == 3
    assert json.loads(result.stdout.strip().splitlines()[-1])["sent"] == 1


def test_cli_verify(tmp_path):
    plan = plan_changes(frames(FULL), CHANGE)
    expected = tmp_path / "exp.syx"
    expected.write_bytes(plan.expected)
    runner = CliRunner()
    assert runner.invoke(app, ["verify", str(expected), str(expected)]).exit_code == 0
    mismatch = runner.invoke(app, ["verify", str(expected), str(FULL)])
    assert mismatch.exit_code == 1
    assert json.loads(mismatch.stdout)["match"] is False


def test_check_changes(tmp_path):
    from es8ctl.apply import check_changes

    plan = plan_changes(frames(FULL), CHANGE)
    expected = list(split_frames(plan.expected))
    applied = check_changes(expected, CHANGE)
    assert applied["applied_count"] == applied["total"] == 1
    missing = check_changes(frames(FULL), CHANGE)
    assert missing["not_applied"] == ["49-1"]
    assert {m["field"] for m in missing["results"][0]["mismatches"]} == {"name", "master_bpm"}
    chain = {"patches": {"6-2": {"loop_chain": "V8746(3//5)21"}}}
    assert check_changes(frames(FULL), chain)["applied_count"] == 1


def test_cli_check_exit_codes(tmp_path):
    changes = tmp_path / "c.json"
    changes.write_text(json.dumps(CHANGE))
    plan = plan_changes(frames(FULL), CHANGE)
    expected = tmp_path / "exp.syx"
    expected.write_bytes(plan.expected)
    runner = CliRunner()
    assert runner.invoke(app, ["check", str(changes), str(expected)]).exit_code == 0
    assert runner.invoke(app, ["check", str(changes), str(FULL)]).exit_code == 1
