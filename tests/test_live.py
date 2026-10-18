"""Tests des commandes directes (étape 4) : messages conformes à l'éditeur officiel."""

import json

import pytest
from typer.testing import CliRunner

from es8ctl import live
from es8ctl.cli import app
from es8ctl.codec import CodecError
from es8ctl.request import editor_mode_message

ON, OFF = editor_mode_message(True), editor_mode_message(False)


def hexes(op):
    return [m.hex(" ") for m in op.messages]


def test_messages_are_wrapped_in_editor_mode():
    for op in (live.select("6-2"), live.rename("0-1", "X"), live.copy("0-1", "0-2"),
               live.exchange("0-1", "0-2"), live.initialize("0-1")):
        assert op.messages[0] == ON and op.messages[-1] == OFF


def test_select_matches_editor_bytes():
    # es_midi.js patchChangeRequest : 7F03 = 00 7F puis 7F01 = n° (6-2 = 49 = 00 31).
    assert hexes(live.select("6-2"))[1:3] == [
        "f0 41 00 00 00 00 14 12 7f 03 00 7f 7f f7",
        "f0 41 00 00 00 00 14 12 7f 01 00 31 4f f7",
    ]


def test_rename_sends_16_chars_then_commit():
    op = live.rename("99-1", "LIVE TEST")
    body = op.messages[1:-1]
    assert len(body) == 17
    assert body[0].hex(" ") == "f0 41 00 00 00 00 14 12 7f 70 00 4c 45 f7"  # « L »
    assert body[15][8:12] == bytes([0x7F, 0x7F, 0x00, 0x20])  # 16e caractère : espace
    assert body[16][8:12] == bytes([0x7F, 0x24, 0x06, 0x18])  # 99-1 = 792 = 06 18
    assert op.touched == [792] and op.detail["name"] == "LIVE TEST       "


def test_copy_exchange_initialize_addresses():
    assert [m[8:12] for m in live.copy("0-8", "99-2").messages[1:-1]] == [
        bytes([0x7F, 0x60, 0x00, 0x07]), bytes([0x7F, 0x22, 0x06, 0x19])]
    assert live.exchange("0-1", "0-2").messages[2][8:10] == bytes([0x7F, 0x23])
    assert live.initialize("0-3").messages[1][8:12] == bytes([0x7F, 0x21, 0x00, 0x02])


@pytest.mark.parametrize(
    "call",
    [lambda: live.rename("0-1", "X" * 17), lambda: live.rename("0-1", "É"),
     lambda: live.copy("0-1", "0-1"), lambda: live.exchange("0-2", "0-2"), lambda: live.select("100-1")],
)
def test_invalid_operations(call):
    with pytest.raises(CodecError):
        call()


def test_expected_after():
    before = {0: b"A", 1: b"B"}
    assert live.expected_after(live.copy("0-1", "0-2"), before) == {0: b"A", 1: b"A"}
    assert live.expected_after(live.exchange("0-1", "0-2"), before) == {0: b"B", 1: b"A"}
    assert live.expected_after(live.rename("0-1", "X"), before) is None


def test_cli_dry_run_sends_nothing():
    result = CliRunner().invoke(app, ["patch", "copy", "0-8", "99-2"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["mode"] == "dry-run" and report["action"] == "copy"


def test_cli_write_requires_port():
    result = CliRunner().invoke(app, ["patch", "init", "99-2", "--write"])
    assert result.exit_code == 2
