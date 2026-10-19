// Chaîne de loops en notation de l'écran (« V8746(3//5)21 ») ↔ arbre éditable.
// La notation suit l'ordre de loop_position, qui va de la SORTIE vers
// l'ENTRÉE ; l'interface la dessine à l'envers (entrée à gauche).
// La validation finale (loops présentes une fois, mixers, blocs) est faite
// côté Python au moment d'ajouter la modification.
//
// Arbre : liste d'éléments, chacun { loop: "V" | "1".."8" } ou
// { par: "(" (MIX) | "[" (SEPARATE), lanes: [liste, liste] } ; une branche
// vide est le signal sec.

const CLOSE = { "(": ")", "[": "]" };
const MAX_PER_KIND = 2;

export function parseChain(text) {
  let i = 0;
  const seq = (stop) => {
    const out = [];
    while (i < text.length) {
      if (stop && text.startsWith(stop, i)) return out;
      const c = text[i];
      if (c === "(" || c === "[") {
        i++;
        const first = seq("//");
        i += 2;
        const second = seq(CLOSE[c]);
        i++;
        out.push({ par: c, lanes: [first, second] });
      } else if (/[V1-8]/i.test(c)) {
        out.push({ loop: c.toUpperCase() });
        i++;
      } else {
        i++;
      }
    }
    return out;
  };
  return seq(null);
}

export function serialize(items) {
  return items.map((it) => (it.loop ? it.loop
    : `${it.par}${serialize(it.lanes[0])}//${serialize(it.lanes[1])}${CLOSE[it.par]}`)).join("");
}

const clone = (items) => JSON.parse(JSON.stringify(items));

/** Retire une loop où qu'elle soit ; un bloc qui n'a plus aucune loop disparaît. */
function removeLoop(items, loop) {
  const out = [];
  for (const it of items) {
    if (it.loop === loop) continue;
    if (it.par) {
      const lanes = it.lanes.map((lane) => removeLoop(lane, loop));
      if (lanes[0].length || lanes[1].length) out.push({ ...it, lanes });
    } else out.push(it);
  }
  return out;
}

/** Cherche la liste (et l'index) qui contient la loop. */
function locate(items, loop) {
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    if (it.loop === loop) return { list: items, index: i };
    if (it.par) for (const lane of it.lanes) { const hit = locate(lane, loop); if (hit) return hit; }
  }
  return null;
}

/**
 * Déplace `loop`, en termes de liste : { before: loop }, { after: loop },
 * { start: true } (côté sortie), { end: true } (côté entrée) ou
 * { lane: [chemin, branche] } (dans une branche vide).
 */
export function moveLoop(text, loop, target) {
  if (target.before === loop || target.after === loop) return text;
  let items = clone(parseChain(text));
  if (target.lane) {
    const [path, k, j] = target.lane;
    const lane = listAt(items, path)[k].lanes[j];
    if (lane.length) return text;
    lane.push({ loop: "__moving__" });
  }
  items = removeLoop(items, loop);
  if (target.lane) {
    const hit = locate(items, "__moving__");
    hit.list[hit.index] = { loop };
  } else if (target.start) {
    items.unshift({ loop });
  } else if (target.end) {
    items.push({ loop });
  } else {
    const hit = locate(items, target.before || target.after);
    if (!hit) return text;
    hit.list.splice(hit.index + (target.after ? 1 : 0), 0, { loop });
  }
  return serialize(items);
}

/** Liste désignée par un chemin : [] = chaîne principale, [i, branche] = branche d'un bloc, etc. */
function listAt(items, path) {
  let list = items;
  for (let k = 0; k < path.length; k += 2) list = list[path[k]].lanes[path[k + 1]];
  return list;
}

const countPar = (items, kind) => items.reduce((n, it) =>
  n + (it.par ? (it.par === kind ? 1 : 0) + countPar(it.lanes[0], kind) + countPar(it.lanes[1], kind) : 0), 0);

/** Encore un bloc MIX possible dans les données ? (deux au plus) */
export const canMix = (text) => countPar(parseChain(text), "(") < MAX_PER_KIND;

/** Met en MIX deux éléments voisins de la chaîne principale (index i et i + 1). */
export function pairUp(text, index) {
  if (!canMix(text)) return text;
  const items = clone(parseChain(text));
  const [a, b] = items.splice(index, 2);
  items.splice(index, 0, { par: "(", lanes: [[a], [b]] });
  return serialize(items);
}

/** Met une loop de la chaîne principale en MIX avec le signal sec. */
export function mixWithDry(text, loop) {
  if (!canMix(text)) return text;
  const items = clone(parseChain(text));
  const i = items.findIndex((it) => it.loop === loop);
  if (i < 0) return text;
  items.splice(i, 1, { par: "(", lanes: [[{ loop }], []] });
  return serialize(items);
}

/** Remplace un bloc de la chaîne principale par ses deux branches à la suite. */
export function dissolve(text, index) {
  const items = clone(parseChain(text));
  const [it] = items.splice(index, 1);
  items.splice(index, 0, ...it.lanes[0], ...it.lanes[1]);
  return serialize(items);
}

/** Encore possible de créer un SEPARATE ? Il se place côté sorties, en tête de liste : un seul à cet endroit. */
export const canSeparate = (text) => {
  const items = parseChain(text);
  return !(items[0] && items[0].par === "[");
};

/**
 * Envoie une loop de la chaîne principale vers les sorties séparées : bloc
 * SEPARATE en tête de liste (juste avant OUT 1 / OUT 2), l'autre branche est
 * le signal sec. Les branches ne sont pas remélangées : pas de mixer utilisé.
 */
export function separate(text, loop) {
  if (!canSeparate(text)) return text;
  const items = clone(parseChain(text));
  const i = items.findIndex((it) => it.loop === loop);
  if (i < 0) return text;
  items.splice(i, 1);
  items.unshift({ par: "[", lanes: [[{ loop }], []] });
  return serialize(items);
}
