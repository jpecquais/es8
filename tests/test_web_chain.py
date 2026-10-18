"""Opérations sur la chaîne de l'interface web (web/chain.js), exécutées sous Node."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from es8ctl.routing import parse

CHAIN_JS = Path(__file__).parents[1] / "src" / "es8ctl" / "web" / "chain.js"

SCRIPT = """
import * as c from %s;
const t = "V8746(3//5)21";
console.log(JSON.stringify({
  roundtrip: c.serialize(c.parseChain(t)),
  nested: c.serialize(c.parseChain("V8[1(2//3)//4]567")),
  before: c.moveLoop(t, "3", { before: "8" }),
  into: c.moveLoop(t, "2", { after: "5" }),
  end: c.moveLoop(t, "V", { end: true }),
  pair: c.pairUp("V87654321", [], 1),
  full: c.freeMarker("(1//2)(3//4)[5//6][7//8]V"),
  dissolve: c.dissolve(t, [], 5),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
def test_chain_operations():
    out = subprocess.run(["node", "--input-type=module", "-e", SCRIPT % json.dumps(CHAIN_JS.as_uri())],
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(out)
    assert r["roundtrip"] == "V8746(3//5)21" and r["nested"] == "V8[1(2//3)//4]567"
    assert r["before"] == "V38746521"  # sortir une loop d'un parallèle le dissout
    assert r["into"] == "V8746(3//52)1"
    assert r["end"] == "8746(3//5)21V"
    assert r["pair"] == "V(8//7)654321" and r["full"] is None
    assert r["dissolve"] == "V8746" + "35" + "21"
    for text in r.values():  # tout résultat est accepté par le moteur
        if text:
            parse(text)
