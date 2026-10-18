"""Tests de la lecture à distance (RQ1), contre un faux ES-8 qui imite l'appareil."""

from pathlib import Path

import mido
import pytest

from es8ctl.codec import parse_es8_bulk_frame, split_frames
from es8ctl.request import (
    editor_mode_message,
    frames_to_syx,
    patch_page,
    read_pages,
    request_message,
)

FIXTURE = Path(__file__).parent / "fixtures" / "es8_bulk_session2_name_A.syx"


def test_messages_match_official_editor():
    # Octets relevés en écoutant l'éditeur officiel, et requête validée sur l'appareil.
    assert editor_mode_message(True).hex(" ") == "f0 41 00 00 00 00 14 12 7f 50 00 01 30 f7"
    assert request_message(16, 17).hex(" ") == "f0 41 00 00 00 00 14 11 00 10 00 01 6f f7"
    with pytest.raises(ValueError):
        request_message(17, 16)


class FakeES8:
    """Répond aux RQ1 comme l'ES-8 : système toujours depuis 0 avec borne de
    fin exclue (sauf au-delà de 15), écho THRU de chaque message reçu, et
    perte possible de trames (interface peu fiable)."""

    def __init__(self, drop_once=()):
        self.data = {parse_es8_bulk_frame(f).counter: f for f in split_frames(FIXTURE.read_bytes())}
        self.queue = []
        self.drop_once = set(drop_once)
        self.requests = []

    # côté sortie (ce que l'hôte envoie)
    def send(self, msg):
        raw = bytes(msg.bytes())
        self.queue.append(raw)  # écho THRU
        if raw[7] == 0x11:
            first, n = raw[8] * 128 + raw[9], raw[10] * 128 + raw[11]
            last = first + n
            self.requests.append((first, last))
            if first <= 15:
                first, last = 0, (last - 1 if last <= 15 else last)
            for c in range(first, last + 1):
                if c in self.drop_once:
                    self.drop_once.discard(c)
                    continue
                if c not in self.data:  # trame jamais émise
                    continue
                self.queue.append(self.data[c])

    # côté entrée (ce que l'hôte reçoit)
    def poll(self):
        return mido.Message.from_bytes(self.queue.pop(0)) if self.queue else None

    def iter_pending(self):
        return iter(())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def es8(monkeypatch):
    device = FakeES8(drop_once={15, 40})
    monkeypatch.setattr(mido, "open_input", lambda p: device)
    monkeypatch.setattr(mido, "open_output", lambda p: device)
    return device


def test_read_system_and_patches_with_retries(es8):
    pages = list(range(8)) + [patch_page(i) for i in range(16)]
    frames, missing = read_pages("dev", "dev", pages, idle_s=0.05)
    assert missing == []
    assert sorted(frames) == list(range(48))
    assert frames_to_syx(frames) == b"".join(es8.data[c] for c in range(48))
    assert es8.requests[0] == (0, 16)  # le système se demande toujours 0..16
    assert len(es8.requests) > 3  # 15 et 40 perdus une fois : relances


def test_read_reports_pages_never_received(monkeypatch):
    device = FakeES8()
    device.data.pop(20)  # la trame n'existe pas : jamais reçue
    monkeypatch.setattr(mido, "open_input", lambda p: device)
    monkeypatch.setattr(mido, "open_output", lambda p: device)
    frames, missing = read_pages("dev", "dev", [patch_page(1), patch_page(2)], idle_s=0.05, retries=1)
    assert missing == [patch_page(2)]
    assert sorted(frames) == [18, 19, 21]
