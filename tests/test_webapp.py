"""Tests du pont web (même code que dans le navigateur sous Pyodide)."""

import asyncio
import json
from pathlib import Path

from es8core import webapp
from es8ctl.cli import library_zip
from es8core.codec import parse_es8_bulk_frame, split_frames

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
        assert f"es8core/{module}.py" in names
    assert not any(n.startswith("es8ctl/") for n in names)  # le navigateur n'a que le moteur


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
    import es8core.apply as apply_mod

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
    import es8core.apply as apply_mod
    from es8core.apply import plan_changes

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


def test_revert_one_element_and_prune_noops():
    webapp.load_syx(FIXTURE.read_bytes())
    webapp.discard()
    sw = json.loads(webapp.patch_detail("0-8"))["fields"]["loop_sw"]
    flipped = [1 - v if i in (0, 3) else v for i, v in enumerate(sw)]
    webapp.stage("0-8", json.dumps({"loop_sw": flipped, "loop_chain": "V12345678"}))
    detail = json.loads(webapp.patch_detail("0-8"))
    assert detail["original"]["chain"] == "V87465321" and detail["original"]["loop_sw"] == sw
    webapp.revert("0-8", "loop_sw", 0)  # un seul élément
    assert json.loads(webapp.patch_detail("0-8"))["fields"]["loop_sw"][0] == sw[0]
    webapp.revert("0-8", "loop_position")  # l'ordre de la chaîne, quelle que soit sa forme
    assert json.loads(webapp.patch_detail("0-8"))["chain"] == "V87465321"
    webapp.revert("0-8", "loop_sw", 3)
    assert json.loads(webapp.pending_summary())["patches"] == []
    # Remettre une valeur à celle de l'appareil retire la modification.
    bpm = json.loads(webapp.patch_detail("0-7"))["bpm"]
    webapp.stage("0-7", json.dumps({"master_bpm": bpm + 1}))
    assert json.loads(webapp.stage("0-7", json.dumps({"master_bpm": bpm})))["patches"] == []
    assert json.loads(webapp.bank_grid())["cells"][6]["pending"] is False


def test_stage_copy_exchanges_patches():
    webapp.load_syx(FIXTURE.read_bytes())
    webapp.discard()
    a, b = (json.loads(webapp.patch_detail(x))["name"] for x in ("0-8", "1-1"))
    summary = json.loads(webapp.stage_copy(json.dumps([["0-8", "1-1"], ["1-1", "0-8"]])))
    assert summary["patches"] == ["0-8", "1-1"]
    assert json.loads(webapp.patch_detail("0-8"))["name"] == b
    assert json.loads(webapp.patch_detail("1-1"))["name"] == a
    assert "error" in json.loads(webapp.stage_copy(json.dumps([["99-8", "0-1"]])))  # 99-8 incomplet ici
    webapp.discard()


def test_labels_and_system_detail():
    names = json.loads(webapp.names())
    assert len(names["assign_target_labels"]) == 46 and names["patch_values"]["output_select"][2] == "1 & 2"
    assert names["ctl_functions"][names["factory_ctl_func"][14]] == "CTL_3"  # CTL In 3 → CTL 3 en usine
    assert names["patch_ranges"]["master_bpm"][0] == 20
    webapp.load_syx(FIXTURE.read_bytes())
    webapp.discard()
    rx = json.loads(webapp.system_detail())["fields"]["midi_setting_rx_ch"]
    webapp.stage_system(json.dumps({"midi_setting_rx_ch": (rx + 1) % 16}))
    sys_detail = json.loads(webapp.system_detail())
    assert sys_detail["original"] == {"midi_setting_rx_ch": rx}
    webapp.revert("system", "midi_setting_rx_ch")
    assert json.loads(webapp.pending_summary())["frames"] == 0


def _namelist_messages(names: list[str]) -> list[bytes]:
    from es8core.codec.roland import checksum

    out = []
    for m in range(100):
        body = [0x20 + (m >> 7), m & 0x7F, *b"".join(n.ljust(16).encode() for n in names[m * 8 : m * 8 + 8])]
        out.append(bytes([0xF0, 0x41, 0x00, 0x00, 0x00, 0x00, 0x14, 0x12, *body, checksum(body), 0xF7]))
    return out


def test_read_names_fills_the_list_before_patches():
    from es8core.request import parse_namelist_message

    names = [f"SONG {i}" for i in range(800)]
    msgs = _namelist_messages(names)
    assert parse_namelist_message(msgs[2])[17] == "SONG 17".ljust(16)
    loop = asyncio.new_event_loop()
    dropped = {5}

    def es8(raw):
        if raw[7] != 0x11:
            return
        first = (raw[8] << 7 | raw[9]) - 4096
        for m in range(first, first + (raw[10] << 7 | raw[11]) + 1):
            if m in dropped:
                dropped.discard(m)  # perdu une fois, redemandé
                continue
            loop.call_soon(webapp.push, msgs[m])

    webapp.state.update(frames={}, dump=None, source=None, fresh=set(), names={})
    webapp.discard()
    webapp.set_sender(lambda data: es8(bytes(data)))
    webapp.transport.queue = asyncio.Queue()
    assert json.loads(loop.run_until_complete(webapp.read_names(idle_s=0.05)))["names"] == 800
    loop.close()
    cells = json.loads(webapp.bank_grid())["cells"]
    assert cells[17] == {"patch": "2-2", "missing": True, "name": "SONG 17", "unnamed": False}


def test_import_export_factory_and_variants():
    from es8core.factory import factory_fields

    webapp.load_syx(FIXTURE.read_bytes())
    webapp.discard()
    # Un .syx dont un patch diffère revient comme modification en attente.
    from es8core.apply import plan_changes

    edited = plan_changes(list(split_frames(FIXTURE.read_bytes())), {"patches": {"0-8": {"master_bpm": 77}}}).expected
    assert len(bytes(webapp.syx_bytes(json.dumps(["0-8", "system"])))) == 18 * 155
    result = json.loads(webapp.import_file(edited, "syx"))
    assert result["patches"] == ["0-8"] and result["imported"] == 1
    webapp.discard()
    assert json.loads(webapp.import_file(webapp.bel_text().encode(), "bel"))["imported"] == 0  # aller-retour .bel
    assert "error" in json.loads(webapp.import_file(b"nope", "bel"))
    assert json.loads(webapp.stage_factory(json.dumps(["0-8"])))["patches"] == ["0-8"]
    assert json.loads(webapp.patch_detail("0-8"))["fields"] == factory_fields()
    webapp.discard()
    summary = json.loads(webapp.transform_variants("0-8", "20-1", 3, prefix="VAR "))
    assert summary["patches"] == ["20-1", "20-2", "20-3"]
    assert json.loads(webapp.patch_detail("20-2"))["name"].startswith("VAR 2")
    webapp.discard()


def test_build_web_produces_a_static_site(tmp_path):
    from typer.testing import CliRunner

    from es8ctl.cli import app

    result = CliRunner().invoke(app, ["build-web", "--out", str(tmp_path / "site")])
    assert result.exit_code == 0, result.output
    for name in ("index.html", "control/index.html", "control/app.js", "control/style.css", "shared/engine.js",
                 "shared/chain.js", "shared/describe.js", "shared/vendor/preact-htm.module.js",
                 "shared/es8core.zip", ".nojekyll"):
        assert (tmp_path / "site" / name).is_file()


def test_web_server_never_serves_outside_its_folders():
    """Un « .. » dans le chemin (envoyé tel quel) ne sort pas des dossiers du site."""
    import http.client
    import socket
    import threading
    import time

    from typer.testing import CliRunner

    from es8ctl.cli import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    threading.Thread(target=lambda: CliRunner().invoke(app, ["web", "--no-open", "--port", str(port)]), daemon=True).start()

    def get(path):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", path)
        res = conn.getresponse()
        return res.status, res.read()

    for _ in range(100):  # le temps que le serveur démarre
        try:
            assert get("/control/")[0] == 200
            break
        except OSError:
            time.sleep(0.05)
    for path in ("/control/../../../../../../../../etc/hosts", "/../../../../../../etc/hosts",
                 "/control/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/hosts"):
        status, body = get(path)
        assert status == 404 and b"localhost" not in body, path


def test_lan_address_is_an_ipv4_or_a_host_name():
    from es8ctl.cli import _lan_address

    address = _lan_address()
    assert address and " " not in address


def test_push_splits_and_joins_sysex():
    """Web MIDI peut livrer des SysEx collés ou en morceaux : la file reçoit des messages entiers."""
    webapp.transport.queue = asyncio.Queue()
    a = bytes([0xF0, 0x41, 0x10, 0x20, 0xF7])
    b = bytes([0xF0, 0x41, 0x11, 0xF7])
    webapp.push(a + b)                       # deux messages dans un événement
    webapp.push(b[:2])                       # un message en deux morceaux…
    webapp.push(bytes([0xF8]) + b[2:])       # … avec un octet temps réel au milieu
    webapp.push(bytes([0x90, 0x40, 0x7F]))   # note : ignorée
    got = [webapp.transport.queue.get_nowait() for _ in range(webapp.transport.queue.qsize())]
    assert got == [a, b, b]
