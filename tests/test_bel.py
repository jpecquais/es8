"""Tests de l'import / export .bel (format de l'éditeur officiel), sur fixture réelle."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from es8core.apply import plan_changes
from es8core.bel import export_bel, import_bel
from es8ctl.cli import app
from es8core.codec import CodecError, frames_by_counter, split_frames
from es8core.diff import load_dump

FIXTURE = Path(__file__).parent / "fixtures" / "es8_bulk_session2_name_A.syx"
NO_SYSTEM = Path(__file__).parent / "fixtures" / "es8_bulk_session1.syx"


@pytest.fixture(scope="module")
def dump():
    return load_dump(FIXTURE)


@pytest.fixture(scope="module")
def document(dump):
    doc, _ = export_bel(dump, frames_by_counter(list(split_frames(FIXTURE.read_bytes()))))
    return json.loads(json.dumps(doc))  # passage par JSON, comme un vrai fichier


def test_export_shape(document):
    assert document["target"] == "ES-8" and document["format"] == 100
    assert len(document["patch"]) == 800
    first = document["patch"][0]
    assert list(first)[:2] == ["ID_PATCH_LOOP_SW_LOOP", "ID_PATCH_LOOP_POSITION"]
    assert first["ID_PATCH_NAME"] == [ord(c) for c in "AAAAAAAAAAAAAAAA"]
    keys = list(document["system"])
    # Ordre de l'éditeur : LINK juste avant les tables de PC.
    assert keys.index("ID_SYSTEM_LINK") + 1 == keys.index("ID_SYSTEM_PC_MAP_BANK0_PC")


def test_export_reconstructs_truncated_last_patch(dump):
    _, warnings = export_bel(dump, frames_by_counter(list(split_frames(FIXTURE.read_bytes()))))
    assert any(w.startswith("99-8") and "identical" in w for w in warnings)


def test_roundtrip_is_empty(document, dump):
    changes, warnings = import_bel(document, dump)
    assert changes == {"patches": {}}


def test_import_edit_flows_into_apply(document, dump, tmp_path):
    edited = json.loads(json.dumps(document))
    edited["patch"][7]["ID_PATCH_MASTER_BPM"] = 140
    edited["patch"][7]["ID_PATCH_NAME"] = [ord(c) for c in "FROM EDITOR     "]
    edited["system"]["ID_SYSTEM_OTHERS_LCD_CONTRAST"] = 6
    changes, _ = import_bel(edited, dump)
    assert changes == {
        "patches": {"0-8": {"master_bpm": 140, "name": "FROM EDITOR     "}},
        "system": {"others_lcd_contrast": 6},
    }
    plan = plan_changes(list(split_frames(FIXTURE.read_bytes())), changes)
    assert len(plan.frames) == 4  # une page patch + la page système 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(target="GT-1000"),
        lambda d: d.update(format=99),
        lambda d: d["patch"].pop(),
        lambda d: d["patch"][0].pop("ID_PATCH_MASTER_BPM"),
        lambda d: d["patch"][0].update(ID_PATCH_UNKNOWN=1),
        lambda d: d["system"].pop("ID_SYSTEM_PANEL_LOCK"),
    ],
)
def test_import_rejects_malformed(document, dump, mutate):
    bad = json.loads(json.dumps(document))
    mutate(bad)
    with pytest.raises(CodecError):
        import_bel(bad, dump)


def test_export_requires_system_block():
    with pytest.raises(CodecError):
        export_bel(load_dump(NO_SYSTEM))


def test_cli_export_import(tmp_path):
    runner = CliRunner()
    bel = tmp_path / "dump.bel"
    result = runner.invoke(app, ["export-bel", str(FIXTURE), "-o", str(bel)])
    assert result.exit_code == 0, result.output
    changes = tmp_path / "changes.json"
    result = runner.invoke(app, ["import-bel", str(bel), "-b", str(FIXTURE), "-o", str(changes)])
    assert result.exit_code == 0, result.output
    assert json.loads(changes.read_text()) == {"patches": {}}
