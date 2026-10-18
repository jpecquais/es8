// Chaîne de loops en notation de l'écran (« V8746(3//5)21 ») ↔ arbre éditable.
// La validation finale (loops présentes une fois, nombre de parallèles) est
// faite par routing.parse côté Python au moment d'ajouter la modification.
//
// Arbre : liste d'éléments, chacun { loop: "V" | "1".."8" } ou
// { par: "(" | "[", lanes: [liste, liste] } ; lanes[0] est la branche écrite
// en premier à l'écran.

const CLOSE = { "(": ")", "[": "]" };
const MAX_PER_SET = 2;

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

/** Retire une loop où qu'elle soit ; dissout un parallèle dont une branche se vide. */
function removeLoop(items, loop) {
  const out = [];
  for (const it of items) {
    if (it.loop === loop) continue;
    if (it.par) {
      const lanes = it.lanes.map((lane) => removeLoop(lane, loop));
      if (!lanes[0].length || !lanes[1].length) out.push(...lanes[0], ...lanes[1]);
      else out.push({ ...it, lanes });
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

/** Déplace `loop` : { before: loop }, { after: loop } ou { end: true } (fin de chaîne). */
export function moveLoop(text, loop, target) {
  if (target.before === loop || target.after === loop) return text;
  const items = removeLoop(clone(parseChain(text)), loop);
  if (target.end) {
    items.push({ loop });
  } else {
    const hit = locate(items, target.before || target.after);
    if (!hit) return text;
    hit.list.splice(hit.index + (target.after ? 1 : 0), 0, { loop });
  }
  return serialize(items);
}

/** Liste désignée par un chemin : [] = chaîne principale, [i, lane] = branche d'un parallèle, etc. */
function listAt(items, path) {
  let list = items;
  for (let k = 0; k < path.length; k += 2) list = list[path[k]].lanes[path[k + 1]];
  return list;
}

const countPar = (items, kind) => items.reduce((n, it) =>
  n + (it.par ? (it.par === kind ? 1 : 0) + countPar(it.lanes[0], kind) + countPar(it.lanes[1], kind) : 0), 0);

/** Jeu de marqueurs libre pour un nouveau parallèle, ou null (quatre au plus). */
export function freeMarker(text) {
  const items = parseChain(text);
  if (countPar(items, "(") < MAX_PER_SET) return "(";
  if (countPar(items, "[") < MAX_PER_SET) return "[";
  return null;
}

/** Met en parallèle deux éléments voisins d'une même liste (index i et i + 1). */
export function pairUp(text, path, index) {
  const marker = freeMarker(text);
  if (!marker) return text;
  const items = clone(parseChain(text));
  const list = listAt(items, path);
  const [a, b] = list.splice(index, 2);
  list.splice(index, 0, { par: marker, lanes: [[a], [b]] });
  return serialize(items);
}

/** Remplace un parallèle par ses deux branches à la suite. */
export function dissolve(text, path, index) {
  const items = clone(parseChain(text));
  const list = listAt(items, path);
  const [it] = list.splice(index, 1);
  list.splice(index, 0, ...it.lanes[0], ...it.lanes[1]);
  return serialize(items);
}
