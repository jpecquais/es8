"""Tests du pont web (même code que dans le navigateur sous Pyodide)."""

import asyncio
import json
from pathlib import Path

from es8ctl import webapp
from es8ctl.cli import library_zip
from es8ctl.codec import parse_es8_bulk_frame, split_frames

FIXTURE = Path(__file__).parent / "fixtures" / "es8_bulk_session2_name_A.syx"


def test_offline_file_flow():
    info = json.loads(webapp.load_syx(FIXTURE.read_bytes()))
    assert info["patches"] == 799
    grid = json.loads(webapp.bank_grid())
    assert grid["source"] == "file" and len(grid["cells"]) == 800
    assert grid["cells"][7]["name"] == "TEMPLATE" and grid["cells"][7]["chain"] == "V87465321"
    assert grid["cells"][799]["missing"] is True  # 99-8 incomplet dans cette fixture
    detail = json.loads(webapp.patch_detail("6-2"))
    assert detail["chain"] == "V8746(3//5)21" and detail["loops"]["L3"] is True
    assert webapp.syx_bytes() == FIXTURE.read_bytes()


def test_device_read_through_web_transport():
    frames = {parse_es8_bulk_frame(f).counter: f for f in split_frames(FIXTURE.read_bytes())}
    loop = asyncio.new_event_loop()

    def es8(raw):  # faux ES-8 : répond aux RQ1 par la boucle d'événements, comme Web MIDI
        if raw[7] != 0x11:
            return
        first = raw[8] * 128 + raw[9]
        last = first + raw[10] * 128 + raw[11]
        if first <= 15:
            first, last = 0, (last - 1 if last <= 15 else last)
        for c in range(first, last + 1):
            if c in frames:
                loop.call_soon(webapp.push, frames[c])

    webapp.set_sender(lambda data: es8(bytes(data)))
    webapp.transport.queue = asyncio.Queue()
    result = json.loads(loop.run_until_complete(webapp.read_device(idle_s=0.05)))
    loop.close()
    assert result["frames"] == 1615 and result["missing_pages"] == [807]
    assert json.loads(webapp.bank_grid())["source"] == "device"


def test_library_zip_has_browser_modules():
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(library_zip())).namelist()
    for module in ("webapp", "session", "request", "patch", "system", "routing", "codec/es8"):
        assert f"es8ctl/{module}.py" in names


class StatefulES8:
    """Faux ES-8 avec mémoire : enregistre les pages DT1 reçues, répond aux RQ1."""

    def __init__(self, loop, drop_page_once=None):
        self.loop = loop
        self.mem = {parse_es8_bulk_frame(f).counter: f for f in split_frames(FIXTURE.read_bytes())}
        self.first_half = None
        self.drop = drop_page_once

    def __call__(self, raw: bytes) -> None:
        if raw[7] == 0x12 and len(raw) == 155:
            counter = raw[8] * 128 + raw[9]
            if counter % 2 == 0:
                self.first_half = raw
            elif self.first_half and self.first_half[8] * 128 + self.first_half[9] == counter - 1:
                if counter - 1 == self.drop:
                    self.drop = None
                    return
                self.mem[counter - 1], self.mem[counter] = self.first_half, raw
        elif raw[7] == 0x11:
            first = raw[8] * 128 + raw[9]
            last = first + raw[10] * 128 + raw[11]
            if first <= 15:
                first, last = 0, (last - 1 if last <= 15 else last)
            for c in range(first, last + 1):
                if c in self.mem:
                    self.loop.call_soon(webapp.push, self.mem[c])


def test_staging_validates_and_previews():
    webapp.load_syx(FIXTURE.read_bytes())
    webapp.discard()
    summary = json.loads(webapp.stage("0-8", json.dumps({"master_bpm": 133, "loop_chain": "V12345678"})))
    assert summary["patches"] == ["0-8"] and summary["frames"] == 2
    assert "error" in json.loads(webapp.stage("0-8", json.dumps({"master_bpm": 999})))
    detail = json.loads(webapp.patch_detail("0-8"))
    assert detail["bpm"] == 133 and detail["chain"] == "V12345678"  # aperçu, pas encore écrit
    assert json.loads(webapp.bank_grid())["cells"][7]["pending"] is True
    swap = json.loads(webapp.transform_swap("6", "7", "6-1..6-2"))
    assert set(swap["patches"]) == {"0-8", "6-1", "6-2"}
    assert json.loads(webapp.discard("6-1"))["patches"] == ["0-8", "6-2"]
    webapp.discard()
    assert json.loads(webapp.pending_summary())["frames"] == 0


def test_write_pending_confirms_and_resends(monkeypatch):
    import es8ctl.apply as apply_mod

    monkeypatch.setattr(apply_mod, "DEFAULT_PAGE_GAP_S", 0.05)
    loop = asyncio.new_event_loop()
    es8 = StatefulES8(loop, drop_page_once=16 + 2 * 7)  # page de 0-8 perdue une fois
    webapp.load_syx(FIXTURE.read_bytes())
    webapp.discard()
    webapp.set_sender(lambda data: es8(bytes(data)))
    webapp.transport.queue = asyncio.Queue()
    webapp.stage("0-8", json.dumps({"name": "WEB EDIT        "}))
    webapp.stage("0-7", json.dumps({"master_bpm": 99}))
    result = json.loads(loop.run_until_complete(webapp.write_pending()))
    loop.close()
    assert result["confirmed"] is True and result["not_confirmed"] == []
    assert [h["pending"] for h in result["history"]] == [1, 0]  # une page renvoyée
    assert json.loads(webapp.pending_summary())["frames"] == 0
    assert json.loads(webapp.patch_detail("0-8"))["name"] == "WEB EDIT        "
    assert es8.mem[16 + 2 * 7] == webapp.state["frames"][16 + 2 * 7]  # appareil == état local


def test_write_rebases_on_device_changes(monkeypatch):
    """L'appareil a changé (au panneau) depuis la lecture : la modification en
    attente s'applique sur la version fraîche, sans écraser ce changement."""
    import es8ctl.apply as apply_mod
    from es8ctl.apply import plan_changes

    monkeypatch.setattr(apply_mod, "DEFAULT_PAGE_GAP_S", 0.05)
    loop = asyncio.new_event_loop()
    es8 = StatefulES8(loop)
    panel = plan_changes(list(es8.mem.values()), {"patches": {"0-8": {"master_bpm": 150}}})
    for f in panel.frames:
        es8.mem[parse_es8_bulk_frame(f).counter] = f  # modifié sur l'appareil, pas dans l'état local
    webapp.load_syx(FIXTURE.read_bytes())
    webapp.discard()
    webapp.set_sender(lambda data: es8(bytes(data)))
    webapp.transport.queue = asyncio.Queue()
    webapp.stage("0-8", json.dumps({"name": "REBASED         "}))
    result = json.loads(loop.run_until_complete(webapp.write_pending()))
    loop.close()
    assert result["confirmed"] is True and result["changed_on_device"] == ["0-8"]
    detail = json.loads(webapp.patch_detail("0-8"))
    assert detail["name"] == "REBASED         " and detail["bpm"] == 150


def test_cache_and_on_demand_reads():
    loop = asyncio.new_event_loop()
    es8 = StatefulES8(loop)
    webapp.load_cached(FIXTURE.read_bytes(), "2026-10-18T10:00:00")
    webapp.discard()
    grid = json.loads(webapp.bank_grid())
    assert grid["source"] == "cache" and grid["cached_at"].startswith("2026-10-18")
    assert all(c["stale"] for c in grid["cells"] if not c.get("missing"))
    webapp.set_sender(lambda data: es8(bytes(data)))
    webapp.transport.queue = asyncio.Queue()
    labels = [f"0-{n}" for n in range(1, 9)]
    result = json.loads(loop.run_until_complete(webapp.read_some(json.dumps(labels), idle_s=0.05)))
    loop.close()
    assert result["frames"] == 16 and result["missing_pages"] == []
    grid = json.loads(webapp.bank_grid())
    assert [c["stale"] for c in grid["cells"][:9]] == [False] * 8 + [True]
    assert grid["fresh_patches"] == 8
