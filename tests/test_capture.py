"""Tests de la capture, sans matériel : simule un port MIDI (fake mido).

Régression clé : Ctrl-C (KeyboardInterrupt) pendant la capture doit
finaliser les fichiers, pas les perdre.
"""

import json

import mido

from es8ctl.capture import record
from es8core.codec import (
    BULK_DATA_LEN,
    BULK_LAST_COUNTER,
    build_es8_bulk_frame,
    build_frame,
)

# Trames valides pour une adresse de 4 octets (défaut de record()).
GOOD = build_frame(0x10, 0x42, 0x12, (0x40, 0x00, 0x00, 0x7F), [0x00])
# Même trame, checksum volontairement faux.
BAD_CHECKSUM = GOOD[:-2] + bytes([0x00, 0xF7])


class FakeMsg:
    def __init__(self, type, data=()):
        self.type = type
        self.data = tuple(data)


class FakeInput:
    """Port d'entrée factice : rend les messages du script, puis les
    exceptions (KeyboardInterrupt) ou None indéfiniment si épuisé."""

    def __init__(self, script):
        self._script = iter(script)

    def poll(self):
        try:
            item = next(self._script)
        except StopIteration:
            return None
        if isinstance(item, BaseException):
            raise item
        return item

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_ctrl_c_finalizes_files(tmp_path, monkeypatch):
    script = [
        FakeMsg("sysex", GOOD[1:-1]),
        FakeMsg("clock"),
        FakeMsg("sysex", BAD_CHECKSUM[1:-1]),
        KeyboardInterrupt(),
    ]
    monkeypatch.setattr(mido, "open_input", lambda port: FakeInput(script))

    result = record("fake", tmp_path)

    assert result.frame_count == 2
    assert result.ignored_count == 1
    # Le .syx contient exactement les trames reçues avant le Ctrl-C.
    assert result.syx_path.read_bytes() == GOOD + BAD_CHECKSUM
    # Sidecar écrit et cohérent, trame invalide signalée explicitement.
    sidecar = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert sidecar["frame_count"] == 2
    assert sidecar["frames"][0]["decoded"]["checksum_valid"] is True
    assert len(result.decode_errors) == 1
    assert "Checksum" in result.decode_errors[0]


def test_timeout_writes_files_even_with_no_traffic(tmp_path, monkeypatch):
    monkeypatch.setattr(mido, "open_input", lambda port: FakeInput([]))

    result = record("fake", tmp_path, timeout_s=0.05)

    assert result.frame_count == 0
    assert result.ignored_count == 0
    assert result.syx_path.exists()
    sidecar = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert sidecar["frame_count"] == 0


def test_frames_flushed_incrementally(tmp_path, monkeypatch):
    """Le .syx doit déjà contenir la première trame même si la capture
    est interrompue avant la fin du script."""

    class ExplodingInput(FakeInput):
        pass

    # Le crash (poll qui lève) survient après la première trame reçue.
    script = [FakeMsg("sysex", GOOD[1:-1]), RuntimeError("crash simulé")]
    monkeypatch.setattr(mido, "open_input", lambda port: ExplodingInput(script))

    try:
        record("fake", tmp_path)
    except RuntimeError:
        pass

    # La trame reçue avant le crash est sur le disque.
    syx_files = list(tmp_path.glob("*.syx"))
    assert len(syx_files) == 1
    assert GOOD in syx_files[0].read_bytes()


def _bulk(counter):
    return FakeMsg("sysex", build_es8_bulk_frame(counter, bytes(BULK_DATA_LEN))[1:-1])


def test_auto_stop_after_tail_if_last_frame_missing(tmp_path, monkeypatch):
    """Si la dernière trame (0C 4F) n'arrive pas, la capture s'arrête
    `tail_s` après l'avant-dernière."""
    script = [_bulk(BULK_LAST_COUNTER - 2), _bulk(BULK_LAST_COUNTER - 1)]
    monkeypatch.setattr(mido, "open_input", lambda port: FakeInput(script))
    progress = []

    result = record("fake", tmp_path, tail_s=0.05, on_frame=lambda n, c: progress.append((n, c)))

    assert result.frame_count == 2
    assert progress == [(1, BULK_LAST_COUNTER - 2), (2, BULK_LAST_COUNTER - 1)]


def test_last_frame_stops_at_once(tmp_path, monkeypatch):
    """À la trame 0C 4F, la capture s'arrête aussitôt : la suite du script
    (qui ferait échouer le test) n'est jamais lue."""
    script = [_bulk(BULK_LAST_COUNTER - 1), _bulk(BULK_LAST_COUNTER), RuntimeError("lu trop loin")]
    monkeypatch.setattr(mido, "open_input", lambda port: FakeInput(script))

    result = record("fake", tmp_path, tail_s=10)

    assert result.frame_count == 2


def test_no_auto_stop_keeps_listening(tmp_path, monkeypatch):
    script = [_bulk(BULK_LAST_COUNTER), FakeMsg("sysex", GOOD[1:-1]), KeyboardInterrupt()]
    monkeypatch.setattr(mido, "open_input", lambda port: FakeInput(script))
    progress = []

    result = record(
        "fake", tmp_path, auto_stop=False, on_frame=lambda n, c: progress.append((n, c))
    )

    assert result.frame_count == 2
    assert progress == [(1, BULK_LAST_COUNTER), (2, None)]
