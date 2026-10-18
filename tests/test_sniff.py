"""Tests du relais enregistreur (faux ports MIDI, aucun matériel)."""

import json

import mido

from es8ctl.sniff import DEVICE_TO_EDITOR, EDITOR_TO_DEVICE, relay


class FakeIn:
    def __init__(self, script):
        self.script = list(script)

    def poll(self):
        if not self.script:
            return None
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOut:
    def __init__(self, sink):
        self.sink = sink

    def send(self, msg):
        self.sink.append(msg)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


REQUEST = mido.Message("sysex", data=[0x41, 0x00, 0x00, 0x00, 0x00, 0x14, 0x11, 0x00, 0x10, 0x5F])
REPLY = mido.Message("sysex", data=[0x41, 0x00, 0x00, 0x00, 0x00, 0x14, 0x12, 0x00, 0x10, 0x01, 0x6F])


def test_relay_forwards_both_ways_and_logs(tmp_path, monkeypatch):
    sent = {"editor": [], "device": []}
    inputs = {"ed": FakeIn([REQUEST, None, KeyboardInterrupt()]), "dev": FakeIn([None, REPLY])}
    monkeypatch.setattr(mido, "open_input", lambda p: inputs[p])
    monkeypatch.setattr(mido, "open_output", lambda p: FakeOut(sent["editor" if p == "ed" else "device"]))

    result = relay("ed", "dev", tmp_path)

    assert sent["device"] == [REQUEST] and sent["editor"] == [REPLY]
    lines = [json.loads(l) for l in result.log_path.read_text().splitlines()]
    assert [l["dir"] for l in lines] == [EDITOR_TO_DEVICE, DEVICE_TO_EDITOR]
    assert lines[0]["roland"]["command"] == "11"
    assert result.summary()["messages"] == {EDITOR_TO_DEVICE: 1, DEVICE_TO_EDITOR: 1}


def test_resolve_port_handles_mojibake_and_prefix():
    from es8ctl.transfer import resolve_port

    ports = ["R\u221a\u00a9seau Session 1", "WIDI Jack Bluetooth"]
    assert resolve_port("Réseau Session 1", ports) == ports[0]
    assert resolve_port("widi", ports) == ports[1]
    assert resolve_port("WIDI Jack Bluetooth", ports) == ports[1]
    assert resolve_port("nope", ports) is None


def test_relay_with_separate_device_input(tmp_path, monkeypatch):
    sent = {"editor": [], "device": []}
    inputs = {"ed": FakeIn([REQUEST, None, None, KeyboardInterrupt()]), "wired": FakeIn([None, REPLY]),
              "widi": FakeIn([RuntimeError("le port WIDI ne doit pas être écouté")])}
    opened = []
    monkeypatch.setattr(mido, "open_input", lambda p: opened.append(p) or inputs[p])
    monkeypatch.setattr(mido, "open_output", lambda p: FakeOut(sent["editor" if p == "ed" else "device"]))

    relay("ed", "widi", tmp_path, device_in_port="wired")

    assert opened == ["ed", "wired"]
    assert sent["device"] == [REQUEST] and sent["editor"] == [REPLY]


def test_relay_drops_thru_echo(tmp_path, monkeypatch):
    """L'écho THRU d'un message de l'éditeur n'est pas renvoyé à l'éditeur."""
    from es8ctl.sniff import ECHO

    sent = {"editor": [], "device": []}
    inputs = {"ed": FakeIn([REQUEST, None, None, None, KeyboardInterrupt()]),
              "dev": FakeIn([None, REQUEST, REPLY])}
    monkeypatch.setattr(mido, "open_input", lambda p: inputs[p])
    monkeypatch.setattr(mido, "open_output", lambda p: FakeOut(sent["editor" if p == "ed" else "device"]))

    result = relay("ed", "dev", tmp_path)

    assert sent["editor"] == [REPLY]
    dirs = [json.loads(l)["dir"] for l in result.log_path.read_text().splitlines()]
    assert dirs == [EDITOR_TO_DEVICE, ECHO, DEVICE_TO_EDITOR]
