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
