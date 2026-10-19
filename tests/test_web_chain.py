"""Opérations sur la chaîne de l'interface web (web/chain.js), exécutées sous Node."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from es8core.routing import parse

CHAIN_JS = Path(__file__).parents[1] / "web" / "shared" / "chain.js"

SCRIPT = """
import * as c from %s;
const t = "V8746(3//5)21";
console.log(JSON.stringify({
  roundtrip: c.serialize(c.parseChain(t)),
  nested: c.serialize(c.parseChain("V8[1(2//3)//4]567")),
  before: c.moveLoop(t, "3", { before: "8" }),
  emptied: c.moveLoop("V87(4//)65321", "4", { start: true }),
  into: c.moveLoop(t, "2", { after: "5" }),
  end: c.moveLoop(t, "V", { end: true }),
  dry: c.moveLoop("V87(4//)65321", "8", { lane: [[], 3, 1] }),
  pair: c.pairUp("V87654321", 1),
  withDry: c.mixWithDry("V87654321", "4"),
  full: c.canMix("(1//2)(3//4)V5678"),
  dissolve: c.dissolve(t, 5),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
def test_chain_operations():
    out = subprocess.run(["node", "--input-type=module", "-e", SCRIPT % json.dumps(CHAIN_JS.as_uri())],
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(out)
    assert r["roundtrip"] == "V8746(3//5)21" and r["nested"] == "V8[1(2//3)//4]567"
    assert r["before"] == "V38746(//5)21"  # la branche vidée devient le signal sec
    assert r["emptied"] == "4V8765321"  # un bloc sans aucune loop disparaît
    assert r["into"] == "V8746(3//52)1"
    assert r["end"] == "8746(3//5)21V"
    assert r["dry"] == "V7(4//8)65321"
    assert r["pair"] == "V(8//7)654321" and r["withDry"] == "V8765(4//)321" and r["full"] is False
    assert r["dissolve"] == "V8746" + "35" + "21"
    for text in r.values():  # tout résultat est accepté par le moteur
        if isinstance(text, str):
            parse(text)
