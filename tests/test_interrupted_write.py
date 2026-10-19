"""Écritures interrompues (question ouverte du plan, §6), simulées avec un faux ES-8.

Le faux ES-8 garde ses pages en mémoire, répond aux lectures (RQ1) et
applique les écritures (DT1). On coupe le lien à différents moments et on
vérifie trois choses : ce que l'appareil contient, ce que l'interface croit
qu'il contient, et ce qui reste en attente. Le comportement réel de l'ES-8
devant une demi-page n'est pas connu : les deux hypothèses sont testées.
"""

import asyncio
import json
from pathlib import Path

import pytest

from es8core import webapp
from es8core.codec import parse_es8_bulk_frame, split_frames

FIXTURE = Path(__file__).parent / "fixtures" / "es8_bulk_session2_name_A.syx"
TARGETS = ["0-1", "0-2", "0-3", "0-4", "0-5", "0-6"]


class FlakyES8:
    """Faux ES-8. `cut(n)` : le lien tombe à partir du n-ième message écrit."""

    def __init__(self, loop, half_page_applies=False):
        self.loop = loop
        self.mem = {parse_es8_bulk_frame(f).counter: f for f in split_frames(FIXTURE.read_bytes())}
        self.half = None
        self.half_page_applies = half_page_applies
        self.written = 0
        self.dead_from = None  # numéro du message d'écriture à partir duquel plus rien ne passe
        self.dead_until = None  # … jusqu'à celui-ci (coupure brève) ; None = définitive
        self.raise_from = None  # le port d'envoi disparaît (exception) à partir de ce message

    def link_up(self):
        n = self.written
        if self.dead_from is None or n < self.dead_from:
            return True
        return self.dead_until is not None and n >= self.dead_until

    def __call__(self, raw: bytes) -> None:
        if raw[7] == 0x12 and len(raw) == 155:
            self.written += 1
            if self.raise_from is not None and self.written >= self.raise_from:
                raise OSError("MIDI port closed")
            if not self.link_up():
                return
            counter = raw[8] * 128 + raw[9]
            if counter % 2 == 0:
                self.half = raw
                if self.half_page_applies:
                    self.mem[counter] = raw  # hypothèse : une demi-page est prise telle quelle
            elif self.half and self.half[8] * 128 + self.half[9] == counter - 1:
                self.mem[counter - 1], self.mem[counter] = self.half, raw
        elif raw[7] == 0x11:
            if not self.link_up():
                return
            first = raw[8] * 128 + raw[9]
            last = first + raw[10] * 128 + raw[11]
            if first <= 15:
                first, last = 0, (last - 1 if last <= 15 else last)
            for c in range(first, last + 1):
                if c in self.mem:
                    self.loop.call_soon(webapp.push, self.mem[c])


@pytest.fixture
def setup(monkeypatch):
    import es8core.apply as apply_mod

    monkeypatch.setattr(apply_mod, "DEFAULT_PAGE_GAP_S", 0.05)
    monkeypatch.setattr(webapp, "DEFAULT_IDLE_S", 0.05)

    def make(**kwargs):
        loop = asyncio.new_event_loop()
        es8 = FlakyES8(loop, **kwargs)
        webapp.load_syx(FIXTURE.read_bytes())
        webapp.discard()
        webapp.set_sender(lambda data: es8(bytes(data)))
        webapp.transport.queue = asyncio.Queue()
        for i, label in enumerate(TARGETS):
            # Un champ dans chaque moitié de page : le tempo (1er message), la forme d'onde (2e).
            webapp.stage(label, json.dumps({"master_bpm": 150 + i, "assign_wave_pedal_form": [0] * 12}))
        return loop, es8

    return make


def device_bpm(es8, label):
    from es8core.codec import parse_patch_label, split_dump, unpack_page
    from es8core.patch import decode_patch

    dump = split_dump(list(es8.mem.values()))
    return decode_patch(unpack_page(dump.patches[parse_patch_label(label)]))["master_bpm"]


def write(loop):
    from es8core import session

    original = session.read_pages_async

    async def fast(*args, **kwargs):  # silences courtes : le test ne doit pas durer
        kwargs["idle_s"] = 0.05
        return await original(*args, **kwargs)

    session.read_pages_async = fast
    webapp.read_pages_async = fast
    try:
        return json.loads(loop.run_until_complete(webapp.write_pending()))
    finally:
        session.read_pages_async = original
        webapp.read_pages_async = original


def test_short_dropout_is_repaired_by_resending(setup):
    loop, es8 = setup()
    es8.dead_from, es8.dead_until = 3, 6  # 3 messages perdus au milieu de l'envoi
    result = write(loop)
    assert result["confirmed"] is True
    assert [device_bpm(es8, label) for label in TARGETS] == [150, 151, 152, 153, 154, 155]
    assert json.loads(webapp.pending_summary())["frames"] == 0


def test_link_lost_for_good_keeps_unconfirmed_changes_pending(setup):
    loop, es8 = setup()
    es8.dead_from = 5  # câble débranché après 2 pages et demie
    result = write(loop)
    assert result["confirmed"] is False
    # L'appareil a les deux premières pages ; la troisième n'a reçu qu'une moitié, ignorée.
    assert [device_bpm(es8, label) for label in TARGETS[:2]] == [150, 151]
    assert device_bpm(es8, "0-3") != 152
    # Sans lien, rien n'a pu être relu : tout reste en attente, rien n'est tenu pour écrit.
    assert json.loads(webapp.pending_summary())["patches"] == TARGETS == result["not_confirmed"]
    # Lien rétabli : la relecture préalable voit 0-1 et 0-2 déjà à jour ; seul le reste part.
    es8.dead_from = None
    second = write(loop)
    assert second["confirmed"] is True and second["frames"] == 2 * 4
    assert [device_bpm(es8, label) for label in TARGETS] == [150, 151, 152, 153, 154, 155]


def test_half_page_taken_by_the_device_is_detected_and_fixed(setup):
    """Hypothèse pessimiste : l'ES-8 prend une demi-page seule (page incohérente)."""
    loop, es8 = setup(half_page_applies=True)
    es8.dead_from, es8.dead_until = 2, 3  # seconde moitié de la 2e page perdue
    result = write(loop)
    assert result["confirmed"] is True
    assert [device_bpm(es8, label) for label in TARGETS] == [150, 151, 152, 153, 154, 155]
    assert result["history"][0]["pending"] >= 1  # la page incohérente a été vue et renvoyée


def test_port_disappearing_mid_write_loses_nothing_locally(setup):
    loop, es8 = setup()
    es8.raise_from = 4
    before = dict(webapp.state["frames"])
    with pytest.raises(OSError):
        write(loop)
    # L'interface ne croit rien d'écrit ; toutes les modifications restent en attente.
    assert json.loads(webapp.pending_summary())["patches"] == TARGETS
    assert all(webapp.state["frames"][c] == before[c] for c in before)
    es8.raise_from = None
    assert write(loop)["confirmed"] is True


def test_no_answer_before_writing_writes_nothing(setup):
    loop, es8 = setup()
    es8.dead_from, es8.written = 0, 0  # l'ES-8 ne répond pas du tout (mauvais port, écran Bulk Dump…)
    result = write(loop)
    assert result["confirmed"] is False and result["frames"] == 0
    assert "nothing was written" in result["error"]
    assert es8.written == 0
