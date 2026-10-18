// es8ctl — interface web (Preact + htm, sans compilation).
// Trois zones : la liste des patchs, le patch (ou la bibliothèque, ou le
// système) au centre, les modifications en attente à droite. Toute
// modification rejoint aussitôt la colonne de droite ; rien n'est envoyé à
// l'ES-8 avant « Écrire ».

import { html, render, useState, useEffect, useRef, useMemo } from "./vendor/preact-htm.module.js";
import * as E from "./engine.js";
import { parseChain, moveLoop, pairUp, dissolve, freeMarker } from "./chain.js";
import { makeDescriber } from "./describe.js";

const { store, call, mutate, toast } = E;

// Disposition des pieds, comme dans l'éditeur officiel.
const BOARD = [
  ["MEM_MAN", "MUTE", "BANK_D", "BANK_U", "NUM_7", "NUM_8"],
  ["NUM_1", "NUM_2", "NUM_3", "NUM_4", "NUM_5", "NUM_6"],
];
const INPUTS = ["CTL_IN_1", "CTL_IN_2", "CTL_IN_3", "CTL_IN_4", "EXP_1", "EXP_2"];
// Source d'assign → pied qui la déclenche directement.
const SOURCE_SLOT = {
  MEM_M: "MEM_MAN", MUTE: "MUTE", BANK_D: "BANK_D", BANK_U: "BANK_U", EXP1: "EXP_1", EXP2: "EXP_2",
  ...Object.fromEntries([1, 2, 3, 4, 5, 6, 7, 8].map((n) => [`NUM${n}`, `NUM_${n}`])),
};

const pad16 = (s) => s.slice(0, 16).padEnd(16);
const bankOf = (label) => Number(label.split("-")[0]);
const labelsOfBank = (b) => [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `${b}-${n}`);
const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
const fmtTime = (iso) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function useStore() {
  const [state, setState] = useState(store.state);
  useEffect(() => store.subscribe(setState), []);
  return state;
}

// ================================================================= application

function App() {
  const s = useStore();
  const prefs = useMemo(E.loadPrefs, []);
  const [view, setView] = useState(prefs.view || "patch");
  const [sel, setSel] = useState(prefs.sel || "0-1");
  const [libSel, setLibSel] = useState([]);
  useEffect(() => E.savePrefs({ view, sel }), [view, sel]);

  const D = useMemo(() => (s.names ? makeDescriber(s.names) : null), [s.names]);
  const open = (label) => { setSel(label); setView("patch"); };

  if (!s.ready) {
    return html`<div class="splash">
      <span class="logo">es8ctl</span>
      ${s.bootError ? html`<p class="error">Le moteur n'a pas pu se charger : ${s.bootError}</p>`
        : html`<p>Chargement du moteur Python…</p><div class="spinner"></div>`}
    </div>`;
  }
  return html`
    <div class="app">
      <${TopBar} s=${s} view=${view} setView=${setView} />
      <div class="body">
        <${Sidebar} s=${s} sel=${sel} onOpen=${open} view=${view} />
        <main class="center">
          ${!s.grid ? html`<${Welcome} s=${s} />`
            : view === "patch" ? html`<${PatchView} s=${s} D=${D} sel=${sel} key=${sel} />`
            : view === "library" ? html`<${LibraryView} s=${s} libSel=${libSel} setLibSel=${setLibSel} onOpen=${open} />`
            : html`<${SystemView} s=${s} D=${D} />`}
        </main>
        <${Tray} s=${s} D=${D} onOpen=${open} />
      </div>
      ${s.toast ? html`<div class="toast ${s.toast.kind}" role="status">
        <span>${s.toast.text}</span><button class="x" onClick=${() => store.set({ toast: null })} aria-label="Fermer">×</button>
      </div>` : null}
    </div>`;
}

// ================================================================= barre du haut

function TopBar({ s, view, setView }) {
  const tabs = [["patch", "Patch"], ["library", "Bibliothèque"], ["system", "Système"]];
  return html`
    <header class="top">
      <span class="logo">es8ctl</span>
      <nav class="tabs" role="tablist">
        ${tabs.map(([id, label]) => html`
          <button role="tab" aria-selected=${view === id} onClick=${() => setView(id)}>${label}</button>`)}
      </nav>
      <span class="grow"></span>
      ${s.busy ? html`<span class="busy"><span>${s.busy.label}</span>
        <progress max=${s.busy.total || 1} value=${s.busy.n}></progress></span>` : null}
      <${Connection} s=${s} />
    </header>`;
}

function Connection({ s }) {
  const [open, setOpen] = useState(false);
  const ref = useRef();
  useEffect(() => {
    const close = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  const device = E.hasDevice();
  const g = s.grid;
  let state = "off", text = "Aucun port MIDI";
  if (s.midi === "unsupported") text = "Web MIDI indisponible";
  else if (s.midi === "denied") text = "Accès MIDI refusé";
  else if (device) { state = "on"; text = E.portName(s.out); }
  let source = "";
  if (g && g.source === "cache") source = `état du ${fmtTime(g.cached_at)}`;
  else if (g && g.source === "file") source = s.fileName || "fichier";
  else if (g && g.source === "device") source = "lu sur l'appareil";
  return html`
    <div class="conn" ref=${ref}>
      <button class="pill ${state}" onClick=${() => setOpen(!open)} aria-expanded=${open}>
        <span class="dot"></span><span>${text}</span>${source ? html`<span class="src">· ${source}</span>` : null}
      </button>
      ${open ? html`<div class="pop">
        ${s.midi === "ok" ? html`
          <label>Sortie vers l'ES-8
            <select value=${s.out} onChange=${(e) => E.choosePorts(e.target.value, s.in)}>
              ${s.outputs.map((p) => html`<option value=${p.id}>${p.name}</option>`)}
            </select></label>
          <label>Entrée depuis l'ES-8
            <select value=${s.in} onChange=${(e) => E.choosePorts(s.out, e.target.value)}>
              ${s.inputs.map((p) => html`<option value=${p.id}>${p.name}</option>`)}
            </select></label>`
        : html`<p class="muted">${s.midi === "unsupported"
            ? "Ce navigateur ne gère pas Web MIDI : utilise Chrome, Edge ou Opera. Les fichiers .syx restent utilisables."
            : s.midi === "denied" ? "Autorise l'accès MIDI (avec SysEx) dans les réglages du site, puis recharge la page."
            : "Recherche des ports MIDI…"}</p>`}
        <button class="btn primary" disabled=${!device || s.busy} onClick=${() => { setOpen(false); E.readDevice(); }}>
          Lire tout l'appareil <small>≈ 2 min 30</small></button>
        <div class="row2">
          <label class="btn">Ouvrir un .syx<input type="file" accept=".syx" hidden
            onChange=${(e) => { e.target.files[0] && E.openSyx(e.target.files[0]); setOpen(false); }} /></label>
          <button class="btn" disabled=${!s.grid} onClick=${() => E.download(E.currentSyx(), `es8_${E.stamp()}.syx`)}>Enregistrer en .syx</button>
        </div>
        <div class="backups">
          <b>Sauvegardes automatiques</b>
          <small class="muted">Faites avant chaque écriture, gardées dans ce navigateur (5 dernières).</small>
          ${s.backups.length ? s.backups.map((b) => html`
            <button class="link" onClick=${() => E.downloadBackup(b)}>${fmtTime(b.date)}</button>`)
            : html`<small class="muted">Aucune pour l'instant.</small>`}
        </div>
      </div>` : null}
    </div>`;
}

function Welcome({ s }) {
  const device = E.hasDevice();
  return html`
    <div class="welcome">
      <h1>Éditeur libre pour l'ES-8</h1>
      <p>Commence par charger l'état de ta pédale. La lecture complète prend environ 2 min 30 ;
        ensuite, la page garde la dernière lecture et ne relit que ce dont tu as besoin.</p>
      <ol>
        <li>Relie l'ES-8 à l'ordinateur en MIDI, dans les deux sens (interface MIDI ou WIDI).</li>
        <li>Mets l'ES-8 sur l'écran de jeu : sur l'écran Bulk Dump, il ignore ce qu'on lui envoie.</li>
        <li>Choisis les ports dans le menu en haut à droite, puis lance la lecture.</li>
      </ol>
      <div class="row2">
        <button class="btn primary" disabled=${!device || s.busy} onClick=${E.readDevice}>Lire l'appareil</button>
        <label class="btn">Ouvrir un fichier .syx<input type="file" accept=".syx" hidden
          onChange=${(e) => e.target.files[0] && E.openSyx(e.target.files[0])} /></label>
      </div>
      ${!device ? html`<p class="muted">${s.midi === "ok" ? "Aucun port MIDI choisi." : "Web MIDI n'est pas disponible : seuls les fichiers .syx sont utilisables."}</p>` : null}
    </div>`;
}

// ================================================================= liste des patchs

/** Banques à afficher et plages de banques repliées (toutes non nommées). */
function useFolds(grid, keep) {
  return useMemo(() => {
    if (!grid) return [];
    const out = [];
    let run = null;
    for (let b = 0; b < 100; b++) {
      const cells = grid.cells.slice(b * 8, b * 8 + 8);
      const quiet = cells.every((c) => c.unnamed && !c.pending) && !keep(b);
      if (quiet) {
        if (run) run.to = b; else { run = { fold: true, from: b, to: b }; out.push(run); }
      } else { run = null; out.push({ bank: b, cells }); }
    }
    return out;
  }, [grid, keep]);
}

function Sidebar({ s, sel, onOpen, view }) {
  const [filter, setFilter] = useState("");
  const [unfolded, setUnfolded] = useState(() => new Set());
  const keep = useMemo(() => (b) => unfolded.has(b) || bankOf(sel) === b, [unfolded, sel]);
  const rows = useFolds(s.grid, keep);
  const device = E.hasDevice();
  const listRef = useRef();

  useEffect(() => {
    const el = listRef.current && listRef.current.querySelector("[aria-current='true']");
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [sel, Boolean(s.grid)]);

  if (!s.grid) return html`<aside class="side"><p class="muted pad">Aucun patch chargé.</p></aside>`;
  const f = filter.trim().toUpperCase();
  const cellRow = (c) => html`
    <button class="p-row ${c.unnamed ? "unnamed" : ""} ${c.pending ? "dirty" : ""} ${c.stale ? "stale" : ""}"
      aria-current=${view === "patch" && c.patch === sel} onClick=${() => onOpen(c.patch)}
      title=${c.missing ? "Patch non lu" : `${c.chain} · ${c.bpm} BPM${c.stale ? " · pas relu depuis l'ouverture" : ""}`}>
      <span class="n">${c.patch}</span>
      <span class="nm">${c.missing ? "non lu" : c.name || "(sans nom)"}</span>
      ${s.grid.current === c.patch ? html`<span class="cur" title="Patch actif sur l'ES-8">●</span>` : html`<span class="mark"></span>`}
    </button>`;

  let body;
  if (f) {
    const hits = s.grid.cells.filter((c) => !c.missing && c.name.toUpperCase().includes(f));
    body = hits.length ? hits.map(cellRow) : html`<p class="muted pad">Aucun patch ne contient « ${filter} ».</p>`;
  } else {
    body = rows.map((r) => r.fold
      ? html`<button class="fold" onClick=${() => setUnfolded(new Set([...unfolded, ...range(r.from, r.to)]))}>
          ${r.from === r.to ? `Banque ${r.from}` : `Banques ${r.from}–${r.to}`} · patchs non nommés</button>`
      : html`<div class="bank">
          <div class="bank-h"><span>Banque ${r.bank}</span>
            ${device ? html`<button class="link" disabled=${s.busy} title="Relit les 8 patchs (≈ 2 s)"
              onClick=${() => E.readSome(labelsOfBank(r.bank), `de la banque ${r.bank}`)}>Relire</button>` : null}</div>
          ${r.cells.map(cellRow)}
        </div>`);
  }
  return html`
    <aside class="side">
      <div class="search"><input type="search" placeholder="Chercher un patch…" value=${filter}
        onInput=${(e) => setFilter(e.target.value)} aria-label="Chercher un patch" /></div>
      <nav class="list" ref=${listRef}>${body}</nav>
    </aside>`;
}

// ================================================================= patch

function PatchView({ s, D, sel }) {
  const d = useMemo(() => call("patch_detail", sel), [sel, s.summary, s.grid]);
  const N = s.names;
  const [openSw, setOpenSw] = useState(null);
  const [openAssign, setOpenAssign] = useState(null);
  if (d.missing) {
    return html`<div class="pad"><h2>${sel}</h2><p class="muted">Ce patch n'a pas été lu.</p>
      ${E.hasDevice() ? html`<button class="btn" onClick=${() => E.readSome([sel], `du patch ${sel}`)}>Le lire</button>` : null}</div>`;
  }
  const f = d.fields;
  const stage = (changes) => mutate("stage", sel, JSON.stringify(changes));
  const setAt = (field, i, v) => { const arr = [...f[field]]; arr[i] = v; return stage({ [field]: arr }); };
  const dirty = (field, i) => {
    const keys = field === "loop_position" ? ["loop_chain", "loop_position"] : [field];
    if (!keys.some((k) => k in d.pending)) return false;
    if (i === undefined || !(field in d.original)) return true;
    return d.original[field][i] !== f[field][i];
  };
  const cell = s.grid.cells.find((c) => c.patch === sel) || {};
  const isDirty = Object.keys(d.pending).length > 0;
  const ctx = { d, f, N, D, stage, setAt, dirty, sel };
  const bpmRange = N.patch_ranges.master_bpm;

  return html`
    <div class="patch">
      <div class="p-head">
        <span class="num">${sel}</span>
        <input class="p-name ${dirty("name") ? "dirty" : ""}" maxlength="16" value=${f.name.trimEnd()} spellcheck="false"
          aria-label="Nom du patch" onChange=${(e) => stage({ name: pad16(e.target.value) })} />
        <label class="mini ${dirty("master_bpm") ? "dirty" : ""}">Tempo
          <input type="number" min=${bpmRange[0]} max=${bpmRange[1]} value=${f.master_bpm}
            onChange=${(e) => stage({ master_bpm: Number(e.target.value) })} /></label>
        <span class="grow"></span>
        <span class="fresh">
          ${s.grid.current === sel ? html`<span class="badge">actif sur l'ES-8</span>` : null}
          ${cell.stale ? html`<span title="Affiché depuis la dernière lecture gardée par le navigateur">pas relu depuis l'ouverture</span>` : null}
          ${E.hasDevice() ? html`<button class="link" disabled=${s.busy} onClick=${() => E.readSome([sel], `du patch ${sel}`)}>Relire</button>` : null}
          ${isDirty ? html`<button class="link" onClick=${() => mutate("discard", sel)}>Annuler les modifications de ce patch</button>` : null}
        </span>
      </div>
      ${d.warnings.length ? html`<p class="warn">${d.warnings.join(" ")}</p>` : null}
      <${Chain} ...${ctx} />
      <${Board} ...${ctx} openSw=${openSw} setOpenSw=${setOpenSw} setOpenAssign=${setOpenAssign} />
      <div class="two">
        <${Assigns} ...${ctx} open=${openAssign} setOpen=${setOpenAssign} />
        <${Midi} ...${ctx} />
      </div>
      <${Advanced} ...${ctx} />
    </div>`;
}

// ----------------------------------------------------------------- chaîne

let dragged = null; // loop en cours de déplacement (glisser-déposer)

const IO_LABELS = {
  input_select: "Entrée", input_buffer: "Buffer d'entrée", output_select: "Sortie", output_buffer: "Buffer de sortie",
  output_gain: "Gain de sortie", mixer_mode: "Mixer", mixer_gain1: "Gain mixer 1", mixer_gain2: "Gain mixer 2",
};

function Chain({ d, f, N, stage, setAt, dirty }) {
  const [io, setIo] = useState(false);
  const text = d.chain;
  const items = useMemo(() => parseChain(text), [text]);
  const loopIndex = (l) => (l === "V" ? 8 : Number(l) - 1);
  const setChain = (t) => { if (t !== text) stage({ loop_chain: t }); };
  const canPair = Boolean(freeMarker(text));

  const clearDrop = (el) => el.classList.remove("drop-l", "drop-r", "drop");
  const drop = (e, target) => {
    e.preventDefault();
    clearDrop(e.currentTarget);
    if (dragged) setChain(moveLoop(text, dragged, target));
    dragged = null;
  };
  const side = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    return e.clientX < r.left + r.width / 2 ? "l" : "r";
  };

  const loopBox = (l) => {
    const i = loopIndex(l), on = Boolean(f.loop_sw[i]), co = Boolean(f.carry_over_loop[i]);
    return html`
      <div class="loop ${on ? "on" : ""} ${l === "V" ? "vol" : ""} ${dirty("loop_sw", i) || dirty("carry_over_loop", i) ? "dirty" : ""}"
        draggable="true" role="button" tabindex="0"
        title=${`${N.loop_labels[N.loops[i]]} · clic : ${on ? "éteindre" : "allumer"} · glisser : déplacer`}
        onClick=${(e) => !e.target.closest(".co") && setAt("loop_sw", i, on ? 0 : 1)}
        onKeyDown=${(e) => (e.key === " " || e.key === "Enter") && (e.preventDefault(), setAt("loop_sw", i, on ? 0 : 1))}
        onDragStart=${(e) => { dragged = l; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", l); }}
        onDragEnd=${() => { dragged = null; }}
        onDragOver=${(e) => { e.preventDefault(); const k = side(e); e.currentTarget.classList.toggle("drop-l", k === "l"); e.currentTarget.classList.toggle("drop-r", k === "r"); }}
        onDragLeave=${(e) => clearDrop(e.currentTarget)}
        onDrop=${(e) => drop(e, side(e) === "l" ? { before: l } : { after: l })}>
        <span class="lbl">${l}</span><span class="led"></span>
        <button class="co ${co ? "on" : ""}" title="Carry-over : garde l'état de la loop au changement de patch"
          onClick=${() => setAt("carry_over_loop", i, co ? 0 : 1)}>CO</button>
      </div>`;
  };

  const list = (arr, path) => arr.map((it, k) => {
    const pair = k + 1 < arr.length && canPair
      ? html`<button class="pair" title="Mettre ces deux éléments en parallèle" onClick=${() => setChain(pairUp(text, path, k))}>∥</button>` : null;
    const node = it.loop ? loopBox(it.loop) : html`
      <div class="par">
        <button class="unpar" title="Remettre en série" onClick=${() => setChain(dissolve(text, path, k))}>×</button>
        ${it.lanes.map((lane, j) => html`<div class="lane">${list(lane, [...path, k, j])}</div>`)}
      </div>`;
    return html`${node}${k + 1 < arr.length ? html`<span class="wire">${pair}</span>` : null}`;
  });

  const v = N.patch_values;
  return html`
    <section class="sect">
      <div class="sect-h"><h4>Chaîne</h4><span class="hint">Clic : allumer ou éteindre · glisser : déplacer · ∥ entre deux loops : parallèle · CO : carry-over</span></div>
      <div class="chain ${dirty("loop_position") ? "dirty" : ""}">
        <button class="jack ${io ? "open" : ""}" onClick=${() => setIo(!io)} title="Entrée, sortie et mixer">
          <b>IN</b><span>${v.input_select[f.input_select]}${f.input_buffer ? " · buffer" : ""}</span></button>
        <span class="wire"></span>
        ${list(items, [])}
        <span class="wire"></span>
        <button class="jack ${io ? "open" : ""}" onClick=${() => setIo(!io)} title="Entrée, sortie et mixer · déposer une loop ici pour la mettre en fin de chaîne"
          onDragOver=${(e) => { e.preventDefault(); e.currentTarget.classList.add("drop"); }}
          onDragLeave=${(e) => clearDrop(e.currentTarget)}
          onDrop=${(e) => drop(e, { end: true })}>
          <b>OUT</b><span>${v.output_select[f.output_select]}${f.output_buffer ? " · buffer" : ""}</span></button>
      </div>
      ${io ? html`<div class="io-edit">
        ${Object.keys(IO_LABELS).map((k) => html`
          <${Pick} label=${IO_LABELS[k]} value=${f[k]} options=${v[k]} dirty=${dirty(k)} onChange=${(x) => stage({ [k]: x })} />`)}
      </div>` : null}
      <${ChainText} text=${text} original=${d.original.chain} onSet=${setChain} />
    </section>`;
}

function ChainText({ text, original, onSet }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(text);
  useEffect(() => setValue(text), [text]);
  return html`
    <div class="notation">
      <span>Notation de l'écran</span>
      ${editing ? html`
        <form onSubmit=${(e) => { e.preventDefault(); onSet(value.trim().toUpperCase()); setEditing(false); }}>
          <input class="mono" value=${value} onInput=${(e) => setValue(e.target.value)} spellcheck="false" autofocus
            aria-label="Chaîne en notation de l'écran" />
          <button class="btn">Appliquer</button><button type="button" class="link" onClick=${() => setEditing(false)}>Annuler</button>
        </form>`
      : html`<code>${text}</code>${original ? html`<span class="muted">avant : <code>${original}</code></span>` : null}
          <button class="link" onClick=${() => setEditing(true)}>Saisir au clavier</button>`}
    </div>`;
}

// ----------------------------------------------------------------- pédalier

/** Assigns déclenchés par un pied : directement, ou via la fonction CTL qu'il porte. */
function slotAssigns(slot, f, N) {
  const idx = N.ctl_slots.indexOf(slot);
  const fn = idx >= 0 ? N.ctl_functions[f.ctl_func[idx]] : null;
  const out = [];
  f.assign_sw.forEach((on, i) => {
    if (!on) return;
    const src = N.assign_sources[f.assign_source[i]];
    if (SOURCE_SLOT[src] === slot || (/^CTL\d$/.test(src) && fn === `CTL_${src[3]}`)) out.push(i);
  });
  return out;
}

function assignSummary(i, f, N, D) {
  const target = N.assign_target_labels[f.assign_target[i]];
  const lo = D.value("assign_target_min", f.assign_target_min[i], f, i);
  const hi = D.value("assign_target_max", f.assign_target_max[i], f, i);
  return `${target} ${lo} ↔ ${hi}`;
}

function Board({ f, N, D, setAt, stage, dirty, openSw, setOpenSw, setOpenAssign }) {
  const card = (slot) => {
    const isExp = slot.startsWith("EXP");
    const idx = isExp ? Number(slot[4]) - 1 : N.ctl_slots.indexOf(slot);
    const fn = isExp ? f.exp_func[idx] : f.ctl_func[idx];
    const custom = !isExp && fn !== N.factory_ctl_func[idx];
    const assigns = slotAssigns(slot, f, N);
    return html`
      <button class="sw ${dirty(isExp ? "exp_func" : "ctl_func", idx) ? "dirty" : ""}"
        aria-pressed=${openSw === slot} onClick=${() => setOpenSw(openSw === slot ? null : slot)}>
        <span class="slot">${isExp ? `EXP ${idx + 1}` : N.ctl_slot_labels[slot]}${custom ? html`<i class="custom" title="Différent du réglage d'usine"></i>` : null}</span>
        <span class="fn ${custom || isExp ? "" : "default"}">${isExp ? `Pédale : ${N.patch_values.exp_func[fn]}` : N.ctl_function_labels[fn]}</span>
        ${assigns.map((i) => html`<span class="tag">Assign ${i + 1} : ${assignSummary(i, f, N, D)}</span>`)}
      </button>`;
  };

  let detail = null;
  if (openSw) {
    const isExp = openSw.startsWith("EXP");
    const k = isExp ? Number(openSw[4]) - 1 : N.ctl_slots.indexOf(openSw);
    const fn = isExp ? f.exp_func[k] : f.ctl_func[k];
    const fnName = isExp ? null : N.ctl_functions[fn];
    const assigns = slotAssigns(openSw, f, N);
    const free = f.assign_sw.indexOf(0);
    const source = isExp ? `EXP${k + 1}` : /^CTL_[1-4]$/.test(fnName) ? `CTL${fnName[4]}`
      : Object.keys(SOURCE_SLOT).find((x) => SOURCE_SLOT[x] === openSw);
    const newAssign = () => {
      const sw = [...f.assign_sw]; sw[free] = 1;
      const src = [...f.assign_source]; src[free] = N.assign_sources.indexOf(source);
      if (stage({ assign_sw: sw, assign_source: src })) setOpenAssign(free);
    };
    detail = html`
      <div class="sw-detail">
        <div class="path">
          <b>${isExp ? `EXP ${k + 1}` : N.ctl_slot_labels[openSw]}</b><i>fait</i>
          ${isExp
            ? html`<select value=${fn} onChange=${(e) => setAt("exp_func", k, Number(e.target.value))} aria-label="Fonction">
                ${N.patch_values.exp_func.map((l, v) => html`<option value=${v}>${l}</option>`)}</select>`
            : html`<select value=${fn} onChange=${(e) => setAt("ctl_func", k, Number(e.target.value))} aria-label="Fonction">
                ${N.ctl_function_labels.map((l, v) => html`<option value=${v}>${l}</option>`)}</select>`}
          ${!isExp && /^CTL_/.test(fnName) ? html`
            <select value=${f.ctl_mod[k]} onChange=${(e) => setAt("ctl_mod", k, Number(e.target.value))} aria-label="Mode">
              <option value="0">Momentané</option><option value="1">Bascule</option></select>` : null}
        </div>
        ${assigns.map((i) => html`<div class="path"><i>et déclenche</i>
          <button class="link" onClick=${() => setOpenAssign(i)}>Assign ${i + 1}</button><i>:</i>
          <span>${assignSummary(i, f, N, D)} (${N.patch_values.assign_mode[f.assign_mode[i]].toLowerCase()})</span></div>`)}
        <div class="muted">
          ${!isExp ? `Réglage d'usine : ${N.ctl_function_labels[N.factory_ctl_func[k]]}. ` : null}
          ${assigns.length ? null : "Aucun assign ne part de ce pied. "}
          ${free >= 0 && source ? html`<button class="link" onClick=${newAssign}>Ajouter un assign déclenché par ce pied</button>` : null}
        </div>
      </div>`;
  }

  return html`
    <section class="sect">
      <div class="sect-h"><h4>Pédalier</h4><span class="hint">Point orange : différent du réglage d'usine · clic : modifier</span></div>
      <div class="board">
        <span class="sep">Pieds</span>
        ${BOARD.flat().map(card)}
        <span class="sep">Entrées CTL et pédales d'expression</span>
        ${INPUTS.map(card)}
      </div>
      ${detail}
    </section>`;
}

// ----------------------------------------------------------------- assigns

const ASSIGN_FIELDS = ["assign_sw", "assign_source", "assign_target", "assign_mode", "assign_target_min",
  "assign_target_max", "assign_act_range_lo", "assign_act_range_hi", "assign_target_cc_ch", "assign_target_cc_no"];

function Assigns({ f, N, D, setAt, stage, dirty, open, setOpen }) {
  const active = f.assign_sw.map((on, i) => (on ? i : -1)).filter((i) => i >= 0);
  const free = f.assign_sw.indexOf(0);
  const ref = useRef();
  useEffect(() => { if (open !== null && ref.current) ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [open]);
  const add = () => { if (setAt("assign_sw", free, 1)) setOpen(free); };

  return html`
    <section class="sect" ref=${ref}>
      <div class="sect-h"><h4>Assigns</h4><span class="hint">${active.length} sur 12</span></div>
      <div class="rows">
        ${active.map((i) => html`
          <div class="item ${open === i ? "open" : ""} ${ASSIGN_FIELDS.some((k) => dirty(k, i)) ? "dirty" : ""}">
            <button class="item-h" onClick=${() => setOpen(open === i ? null : i)}>
              <span class="k">${i + 1}</span>
              <span>${N.assign_source_labels[f.assign_source[i]]} → <b>${assignSummary(i, f, N, D)}</b></span>
              <span class="muted">${N.patch_values.assign_mode[f.assign_mode[i]]}</span>
            </button>
            ${open === i ? html`<${AssignEditor} i=${i} f=${f} N=${N} setAt=${setAt} stage=${stage} dirty=${dirty}
              onRemove=${() => { setAt("assign_sw", i, 0); setOpen(null); }} />` : null}
          </div>`)}
        ${free >= 0 ? html`<button class="add" onClick=${add}>+ Ajouter un assign (${12 - active.length} libres)</button>`
          : html`<p class="muted">Les 12 assigns sont utilisés.</p>`}
      </div>
    </section>`;
}

function AssignEditor({ i, f, N, setAt, stage, dirty, onRemove }) {
  const values = N.assign_target_values[f.assign_target[i]];
  const target = N.assign_targets[f.assign_target[i]];
  const numRange = target === "MASTER_BPM" ? [20, 250] : [0, 127];
  const setTarget = (t) => {
    const vals = N.assign_target_values[t];
    const bpm = N.assign_targets[t] === "MASTER_BPM";
    const tg = [...f.assign_target], lo = [...f.assign_target_min], hi = [...f.assign_target_max];
    tg[i] = t;
    lo[i] = vals ? 0 : bpm ? 60 : 0;
    hi[i] = vals ? vals.length - 1 : bpm ? 120 : 127;
    stage({ assign_target: tg, assign_target_min: lo, assign_target_max: hi });
  };
  const val = (field) => values
    ? html`<select value=${f[field][i]} onChange=${(e) => setAt(field, i, Number(e.target.value))}>
        ${values.map((l, v) => html`<option value=${v}>${l}</option>`)}</select>`
    : html`<input type="number" min=${numRange[0]} max=${numRange[1]} value=${f[field][i]}
        onChange=${(e) => setAt(field, i, Number(e.target.value))} />`;
  const continuous = ["EXP1", "EXP2", "INT", "WAV", "CC"].includes(N.assign_sources[f.assign_source[i]]);
  const cls = (field) => (dirty(field, i) ? "dirty" : "");
  return html`
    <div class="editor">
      <label class=${cls("assign_source")}>Déclenché par
        <select value=${f.assign_source[i]} onChange=${(e) => setAt("assign_source", i, Number(e.target.value))}>
          ${N.assign_source_labels.map((l, v) => html`<option value=${v}>${l}</option>`)}</select></label>
      <label class=${cls("assign_target")}>Agit sur
        <select value=${f.assign_target[i]} onChange=${(e) => setTarget(Number(e.target.value))}>
          ${N.assign_target_labels.map((l, v) => html`<option value=${v}>${l}</option>`)}</select></label>
      <label class=${cls("assign_target_min")}>Au repos ${val("assign_target_min")}</label>
      <label class=${cls("assign_target_max")}>Actionné ${val("assign_target_max")}</label>
      <label class=${cls("assign_mode")}>Mode
        <select value=${f.assign_mode[i]} onChange=${(e) => setAt("assign_mode", i, Number(e.target.value))}>
          <option value="0">Momentané</option><option value="1">Bascule</option></select></label>
      ${continuous ? html`
        <label class=${cls("assign_act_range_lo")}>Plage basse
          <input type="number" min="0" max="126" value=${f.assign_act_range_lo[i]} onChange=${(e) => setAt("assign_act_range_lo", i, Number(e.target.value))} /></label>
        <label class=${cls("assign_act_range_hi")}>Plage haute
          <input type="number" min="1" max="127" value=${f.assign_act_range_hi[i]} onChange=${(e) => setAt("assign_act_range_hi", i, Number(e.target.value))} /></label>` : null}
      ${target === "MIDI" ? html`
        <label class=${cls("assign_target_cc_ch")}>Canal MIDI
          <input type="number" min="1" max="16" value=${f.assign_target_cc_ch[i] + 1} onChange=${(e) => setAt("assign_target_cc_ch", i, Number(e.target.value) - 1)} /></label>
        <label class=${cls("assign_target_cc_no")}>Numéro de CC
          <input type="number" min="0" max="127" value=${f.assign_target_cc_no[i]} onChange=${(e) => setAt("assign_target_cc_no", i, Number(e.target.value))} /></label>` : null}
      <button class="link danger" onClick=${onRemove}>Désactiver cet assign</button>
    </div>`;
}

// ----------------------------------------------------------------- MIDI

const MIDI_FIELDS = ["midi_tx_ch", "midi_pc", "midi_pc_bank_msb", "midi_pc_bank_lsb", "midi_ctl1_cc", "midi_ctl1_cc_val", "midi_ctl2_cc", "midi_ctl2_cc_val"];

function Midi({ f, N, setAt, dirty }) {
  const [open, setOpen] = useState(null);
  const used = f.midi_tx_ch.map((ch, i) => (ch ? i : -1)).filter((i) => i >= 0);
  const free = f.midi_tx_ch.indexOf(0);
  const v = N.patch_values;
  const summary = (i) => [
    f.midi_pc[i] ? `PC ${v.midi_pc[f.midi_pc[i]]}` : null,
    f.midi_pc_bank_msb[i] || f.midi_pc_bank_lsb[i] ? `banque ${v.midi_pc_bank_msb[f.midi_pc_bank_msb[i]]} / ${v.midi_pc_bank_lsb[f.midi_pc_bank_lsb[i]]}` : null,
    f.midi_ctl1_cc[i] ? `${v.midi_ctl1_cc[f.midi_ctl1_cc[i]]} = ${f.midi_ctl1_cc_val[i]}` : null,
    f.midi_ctl2_cc[i] ? `${v.midi_ctl2_cc[f.midi_ctl2_cc[i]]} = ${f.midi_ctl2_cc_val[i]}` : null,
  ].filter(Boolean).join(" · ") || "rien d'envoyé";
  const sel = (field, i) => html`<select value=${f[field][i]} onChange=${(e) => setAt(field, i, Number(e.target.value))}>
    ${v[field].map((l, x) => html`<option value=${x}>${l}</option>`)}</select>`;
  const num = (field, i) => html`<input type="number" min="0" max="127" value=${f[field][i]} aria-label="Valeur"
    onChange=${(e) => setAt(field, i, Number(e.target.value))} />`;
  return html`
    <section class="sect">
      <div class="sect-h"><h4>MIDI à l'appel du patch</h4><span class="hint">${used.length} sur 8</span></div>
      <div class="rows">
        ${used.map((i) => html`
          <div class="item ${open === i ? "open" : ""} ${MIDI_FIELDS.some((k) => dirty(k, i)) ? "dirty" : ""}">
            <button class="item-h" onClick=${() => setOpen(open === i ? null : i)}>
              <span class="k">Canal ${v.midi_tx_ch[f.midi_tx_ch[i]]}</span><span>${summary(i)}</span></button>
            ${open === i ? html`<div class="editor">
              <label>Canal ${sel("midi_tx_ch", i)}</label>
              <label>Program Change ${sel("midi_pc", i)}</label>
              <label>Banque MSB ${sel("midi_pc_bank_msb", i)}</label>
              <label>Banque LSB ${sel("midi_pc_bank_lsb", i)}</label>
              <label>CC 1 <span class="pair-in">${sel("midi_ctl1_cc", i)}${num("midi_ctl1_cc_val", i)}</span></label>
              <label>CC 2 <span class="pair-in">${sel("midi_ctl2_cc", i)}${num("midi_ctl2_cc_val", i)}</span></label>
              <button class="link danger" onClick=${() => { setAt("midi_tx_ch", i, 0); setOpen(null); }}>Supprimer ce message</button>
            </div>` : null}
          </div>`)}
        ${free >= 0 ? html`<button class="add" onClick=${() => { if (setAt("midi_tx_ch", free, 1)) setOpen(free); }}>
          + Ajouter un message (${8 - used.length} libres)</button>` : null}
      </div>
    </section>`;
}

// ----------------------------------------------------------------- réglages avancés

function Pick({ label, value, options, dirty, onChange }) {
  return html`<label class="pick ${dirty ? "dirty" : ""}">${label}
    <select value=${value} onChange=${(e) => onChange(Number(e.target.value))}>
      ${options.map((l, v) => html`<option value=${v}>${l}</option>`)}</select></label>`;
}

const LEDS = ["num1", "num2", "num3", "num4", "num5", "num6", "num7", "num8", "bank_d", "bank_u"];
const ledName = (k) => k.replace("num", "Number ").replace("bank_d", "Bank ▼").replace("bank_u", "Bank ▲");

function Advanced({ f, N, stage, setAt, dirty }) {
  const [raw, setRaw] = useState("");
  const v = N.patch_values;
  const submitRaw = (e) => {
    e.preventDefault();
    let changes;
    try { changes = JSON.parse(raw); } catch (err) { toast(`JSON invalide : ${err.message}`, "error"); return; }
    if (stage(changes)) setRaw("");
  };
  return html`
    <details class="sect adv">
      <summary>Réglages avancés : horloge MIDI, LED, état des CTL à l'appel, tous les champs</summary>
      <div class="io-edit">
        <${Pick} label="Horloge MIDI" value=${f.midi_clock_out} options=${v.midi_clock_out} dirty=${dirty("midi_clock_out")}
          onChange=${(x) => stage({ midi_clock_out: x })} />
        ${f.midi_transmit.map((t, i) => html`<${Pick} label=${`Envoi du message MIDI ${i + 1}`} value=${t} options=${v.midi_transmit}
          dirty=${dirty("midi_transmit", i)} onChange=${(x) => setAt("midi_transmit", i, x)} />`)}
      </div>
      <div class="sect-h"><h4>LED à l'appel du patch</h4></div>
      <div class="toggles">
        ${LEDS.map((k) => html`<label class="toggle ${dirty(`led_${k}`) ? "dirty" : ""}">
          <input type="checkbox" checked=${Boolean(f[`led_${k}`])} onChange=${(e) => stage({ [`led_${k}`]: e.target.checked ? 1 : 0 })} />
          ${ledName(k)}</label>`)}
      </div>
      <div class="sect-h"><h4>CTL et EXP à l'appel du patch</h4></div>
      <div class="io-edit">
        ${["ctl1", "ctl2", "ctl3", "ctl4", "ctl5", "ctl6", "exp1", "exp2"].map((k) => html`
          <label class="pick ${dirty(k) ? "dirty" : ""}">${k.toUpperCase()}
            <input type="number" min=${N.patch_ranges[k][0]} max=${N.patch_ranges[k][1]} value=${f[k]}
              onChange=${(e) => stage({ [k]: Number(e.target.value) })} /></label>`)}
      </div>
      <form class="raw" onSubmit=${submitRaw}>
        <label>Autres champs, en JSON
          <textarea rows="3" spellcheck="false" value=${raw} onInput=${(e) => setRaw(e.target.value)}
            placeholder='{"assign_wave_pedal_rate": [7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7]}'></textarea></label>
        <button class="btn" disabled=${!raw.trim()}>Ajouter aux modifications</button>
      </form>
      <details><summary>Tous les champs du patch</summary><pre>${JSON.stringify(f, null, 1)}</pre></details>
    </details>`;
}

// ================================================================= bibliothèque

function LibraryView({ s, libSel, setLibSel, onOpen }) {
  const [unfolded, setUnfolded] = useState(() => new Set());
  const keep = useMemo(() => (b) => unfolded.has(b), [unfolded]);
  const rows = useFolds(s.grid, keep);
  const last = useRef(null);
  const selSet = new Set(libSel);
  const order = s.grid.cells.map((c) => c.patch);

  const click = (e, label) => {
    if (e.shiftKey && last.current) {
      const [a, b] = [order.indexOf(last.current), order.indexOf(label)].sort((x, y) => x - y);
      setLibSel([...new Set([...libSel, ...order.slice(a, b + 1)])]);
    } else if (e.metaKey || e.ctrlKey) {
      setLibSel(selSet.has(label) ? libSel.filter((x) => x !== label) : [...libSel, label]);
    } else {
      setLibSel(selSet.has(label) && libSel.length === 1 ? [] : [label]);
    }
    last.current = label;
  };
  const exchange = (a, b) => {
    if (!a || a === b) return;
    if (mutate("stage_copy", JSON.stringify([[a, b], [b, a]]))) toast(`Échange ${a} ↔ ${b} ajouté aux modifications.`, "ok", 3000);
  };

  return html`
    <div class="library">
      <div class="p-head"><h2>Bibliothèque</h2><span class="grow"></span>
        <span class="fresh">Clic : choisir · Maj-clic : plage · ⌘/Ctrl-clic : ajouter · double-clic : ouvrir · glisser sur un autre : échanger</span></div>
      <${SelectionBar} s=${s} sel=${libSel} clear=${() => setLibSel([])} onOpen=${onOpen} />
      <div class="lib">
        ${rows.map((r) => r.fold
          ? html`<button class="fold" onClick=${() => setUnfolded(new Set([...unfolded, ...range(r.from, r.to)]))}>
              ${r.from === r.to ? `Banque ${r.from}` : `Banques ${r.from}–${r.to}`} · patchs non nommés · afficher</button>`
          : html`<div class="lib-row">
              <button class="bn" title="Choisir toute la banque" onClick=${() => setLibSel(labelsOfBank(r.bank))}>${r.bank}</button>
              ${r.cells.map((c) => html`
                <button class="cell ${c.unnamed ? "unnamed" : ""} ${c.pending ? "dirty" : ""} ${c.stale ? "stale" : ""}"
                  aria-pressed=${selSet.has(c.patch)} draggable=${!c.missing}
                  title=${c.missing ? `${c.patch} · non lu` : `${c.patch} · ${c.chain} · ${c.bpm} BPM`}
                  onClick=${(e) => click(e, c.patch)} onDblClick=${() => onOpen(c.patch)}
                  onDragStart=${(e) => e.dataTransfer.setData("text/plain", c.patch)}
                  onDragOver=${(e) => { e.preventDefault(); e.currentTarget.classList.add("drop"); }}
                  onDragLeave=${(e) => e.currentTarget.classList.remove("drop")}
                  onDrop=${(e) => { e.preventDefault(); e.currentTarget.classList.remove("drop"); exchange(e.dataTransfer.getData("text/plain"), c.patch); }}>
                  <span class="n">${c.patch}</span><span class="nm">${c.missing ? "non lu" : c.name || "(sans nom)"}</span>
                </button>`)}
            </div>`)}
      </div>
    </div>`;
}

function SelectionBar({ s, sel, clear, onOpen }) {
  const N = s.names;
  const [action, setAction] = useState("ctl");
  const [slot, setSlot] = useState("CTL_IN_3");
  const [fn, setFn] = useState("BPM");
  const [bpm, setBpm] = useState(120);
  const [a, setA] = useState("L6");
  const [b, setB] = useState("L7");
  const [dest, setDest] = useState("");
  const [raw, setRaw] = useState("");
  if (!sel.length) {
    return html`<div class="selbar"><span>Choisis des patchs pour leur appliquer un réglage, échanger des loops ou les copier ailleurs.
      Un clic sur un numéro de banque la choisit en entier.</span></div>`;
  }
  const scope = sel.join(",");
  const n = `${sel.length} patch${sel.length > 1 ? "s" : ""}`;
  const done = (ok, text) => ok && toast(text, "ok", 3000);
  const apply = (e) => {
    e.preventDefault();
    if (action === "ctl") {
      done(mutate("transform_set", JSON.stringify([`ctl_func[${slot}]=${fn}`]), scope),
        `${N.ctl_slot_labels[slot]} → ${N.ctl_function_labels[N.ctl_functions.indexOf(fn)]} sur ${n}.`);
    } else if (action === "bpm") {
      done(mutate("transform_set", JSON.stringify([`master_bpm=${bpm}`]), scope), `Tempo ${bpm} BPM sur ${n}.`);
    } else if (action === "swap") {
      done(mutate("transform_swap", a, b, scope), `Échange ${N.loop_labels[a]} ↔ ${N.loop_labels[b]} sur ${n}.`);
    } else if (action === "copy") {
      const order = s.grid.cells.map((c) => c.patch);
      const start = order.indexOf(dest.trim());
      if (start < 0) { toast(`Destination inconnue : « ${dest} ». Exemple : 20-1.`, "error"); return; }
      const sorted = [...sel].sort((x, y) => order.indexOf(x) - order.indexOf(y));
      if (start + sorted.length > order.length) { toast("Pas assez de place après la destination.", "error"); return; }
      const pairs = sorted.map((src, k) => [src, order[start + k]]);
      done(mutate("stage_copy", JSON.stringify(pairs)), `${n} copié${sel.length > 1 ? "s" : ""} vers ${pairs[0][1]}–${pairs[pairs.length - 1][1]}.`);
    } else {
      const lines = raw.split(/[\n;]/).map((l) => l.trim()).filter(Boolean);
      if (lines.length) done(mutate("transform_set", JSON.stringify(lines), scope), `${lines.length} affectation(s) sur ${n}.`);
    }
  };
  const loops = N.loops.map((l) => html`<option value=${l}>${N.loop_labels[l]}</option>`);
  return html`
    <form class="selbar" onSubmit=${apply}>
      <b>${n}</b>
      <select value=${action} onChange=${(e) => setAction(e.target.value)} aria-label="Action">
        <option value="ctl">Changer la fonction d'un pied</option>
        <option value="bpm">Régler le tempo</option>
        <option value="swap">Échanger deux loops</option>
        <option value="copy">Copier vers…</option>
        <option value="raw">Affecter des champs (syntaxe du CLI)</option>
      </select>
      ${action === "ctl" ? html`
        <select value=${slot} onChange=${(e) => setSlot(e.target.value)} aria-label="Pied">
          ${N.ctl_slots.map((x) => html`<option value=${x}>${N.ctl_slot_labels[x]}</option>`)}</select>
        <span>fait</span>
        <select value=${fn} onChange=${(e) => setFn(e.target.value)} aria-label="Fonction">
          ${N.ctl_functions.map((x, i) => html`<option value=${x}>${N.ctl_function_labels[i]}</option>`)}</select>` : null}
      ${action === "bpm" ? html`<input type="number" min="20" max="250" value=${bpm} onInput=${(e) => setBpm(Number(e.target.value))} aria-label="Tempo" /><span>BPM</span>` : null}
      ${action === "swap" ? html`<select value=${a} onChange=${(e) => setA(e.target.value)} aria-label="Première loop">${loops}</select><span>↔</span>
        <select value=${b} onChange=${(e) => setB(e.target.value)} aria-label="Seconde loop">${loops}</select>
        <small class="muted">interrupteurs, carry-over, assigns et place dans la chaîne</small>` : null}
      ${action === "copy" ? html`<span>à partir de</span><input class="short" placeholder="20-1" value=${dest} onInput=${(e) => setDest(e.target.value)} aria-label="Destination" />` : null}
      ${action === "raw" ? html`<input class="wide" placeholder="ctl_func[NUM_8]=BPM; master_bpm=120" value=${raw} onInput=${(e) => setRaw(e.target.value)} spellcheck="false" aria-label="Affectations" />` : null}
      <button class="btn primary">Ajouter aux modifications</button>
      <span class="grow"></span>
      ${sel.length === 1 ? html`<button type="button" class="btn" onClick=${() => onOpen(sel[0])}>Ouvrir</button>` : null}
      ${E.hasDevice() ? html`<button type="button" class="btn" disabled=${s.busy} onClick=${() => E.readSome(sel, "de la sélection")}>Relire</button>` : null}
      <button type="button" class="link" onClick=${clear}>Tout désélectionner</button>
    </form>`;
}

// ================================================================= système

function SystemView({ s }) {
  const sys = useMemo(() => call("system_detail"), [s.summary, s.grid]);
  const N = s.names;
  if (!sys) return html`<div class="pad"><h2>Système</h2><p class="muted">Le bloc système n'a pas été lu.</p></div>`;
  const f = sys.fields;
  const set = (k, v) => mutate("stage_system", JSON.stringify({ [k]: v }));
  return html`
    <div class="system">
      <div class="p-head"><h2>Système</h2><span class="grow"></span>
        <span class="fresh">Réglages communs à tous les patchs
          ${E.hasDevice() ? html`<button class="link" disabled=${s.busy} onClick=${() => E.readSome(["system"], "du système")}>Relire</button>` : null}
          ${Object.keys(sys.pending).length ? html`<button class="link" onClick=${() => mutate("discard", "system")}>Annuler les modifications</button>` : null}
        </span></div>
      <div class="sys">
        ${N.system_groups.map(([title, fields]) => html`
          <section class="card"><h4>${title}</h4>
            ${fields.filter(([k]) => k in f).map(([k, label]) => {
              const opts = N.system_values[k];
              const [lo, hi] = N.system_ranges[k] || [0, 127];
              return html`<label class="kv ${k in sys.pending ? "dirty" : ""}"><span>${label}</span>
                ${opts ? html`<select value=${f[k]} onChange=${(e) => set(k, Number(e.target.value))}>
                    ${opts.map((l, v) => html`<option value=${v}>${l}</option>`)}</select>`
                  : html`<input type="number" min=${lo} max=${hi} value=${f[k]} onChange=${(e) => set(k, Number(e.target.value))} />`}
              </label>`;
            })}
          </section>`)}
      </div>
      <p class="muted">La table des Program Change et les contrôleurs en mode système ne sont pas encore éditables ici
        (en ligne de commande : <code>es8ctl apply</code>).</p>
    </div>`;
}

// ================================================================= modifications en attente

function systemLine(c, N, D) {
  const entry = N.system_groups.flatMap(([, fields]) => fields).find(([k]) => k === c.field);
  return { field: c.field, index: null, what: entry ? entry[1] : c.field, from: D.systemValue(c.field, c.old), to: D.systemValue(c.field, c.new) };
}

function Tray({ s, D, onOpen }) {
  const [confirm, setConfirm] = useState(null); // "write" | "discard"
  const N = s.names;
  const groups = useMemo(() => {
    if (!D) return [];
    const by = new Map();
    const fieldsOf = {};
    for (const c of s.summary.changes) {
      if (c.target !== "system" && !fieldsOf[c.target]) fieldsOf[c.target] = call("patch_detail", c.target).fields;
      const lines = c.target === "system" ? [systemLine(c, N, D)] : D.lines(c, fieldsOf[c.target]);
      if (!by.has(c.target)) by.set(c.target, []);
      by.get(c.target).push(...lines);
    }
    return [...by.entries()];
  }, [s.summary, D]);
  const total = groups.reduce((n, [, l]) => n + l.length, 0);
  const nameOf = (t) => (s.grid && s.grid.cells.find((c) => c.patch === t) || {}).name || "";
  const device = E.hasDevice();
  useEffect(() => { if (!total) setConfirm(null); }, [total]);

  return html`
    <aside class="tray">
      <div class="tray-h"><h4>Modifications <span class="count">${total}</span></h4>
        <small>Rien n'est envoyé à l'ES-8 avant « Écrire ».</small></div>
      <div class="tray-list">
        ${total ? groups.map(([target, lines]) => html`
          <div class="t-group">
            ${target === "system" ? html`<span class="gh">Système</span>`
              : html`<button class="gh" onClick=${() => onOpen(target)}>${target} · ${nameOf(target)}</button>`}
            ${lines.map((l) => html`
              <div class="t-item">
                <span class="what">${l.what}</span>
                <span class="diff">${l.from} → <b>${l.to}</b></span>
                <button title="Annuler cette modification" aria-label="Annuler cette modification"
                  onClick=${() => mutate("revert", target, l.field, l.index ?? null)}>↶</button>
              </div>`)}
          </div>`)
        : html`<p class="empty">Aucune modification. Ce que tu changes au centre s'ajoute ici, patch par patch, avec la valeur d'avant.</p>`}
      </div>
      <div class="tray-f">
        ${s.busy ? html`<div class="progress"><span>${s.busy.label} · ${s.busy.n} / ${s.busy.total}</span>
            <progress max=${s.busy.total || 1} value=${s.busy.n}></progress></div>`
        : confirm === "write" ? html`
            <p class="note">L'ES-8 doit être sur l'écran de jeu (sur l'écran Bulk Dump, appuie sur EXIT). Les patchs visés sont relus
              juste avant l'envoi, puis vérifiés. Une sauvegarde de l'état actuel est faite d'abord.</p>
            <button class="btn primary" onClick=${() => { setConfirm(null); E.writePending(); }}>Confirmer l'écriture</button>
            <button class="link" onClick=${() => setConfirm(null)}>Annuler</button>`
        : confirm === "discard" ? html`
            <button class="btn danger" onClick=${() => { setConfirm(null); mutate("discard"); }}>Oui, tout annuler</button>
            <button class="link" onClick=${() => setConfirm(null)}>Garder les modifications</button>`
        : html`
            <button class="btn primary" disabled=${!total || !device} onClick=${() => setConfirm("write")}>Écrire sur l'ES-8</button>
            <small class="muted">${total
              ? `${s.summary.frames / 2} page(s) · environ ${Math.max(1, s.summary.estimated_s)} s d'envoi, plus la relecture et la vérification.`
              : "Relecture des patchs visés, envoi, vérification."}${total && !device ? " Choisis les ports MIDI pour écrire." : ""}</small>
            ${total ? html`<button class="link" onClick=${() => setConfirm("discard")}>Tout annuler</button>` : null}`}
      </div>
    </aside>`;
}

// ================================================================= démarrage

render(html`<${App} />`, document.getElementById("root"));
E.boot();

// ↑ / ↓ : patch précédent ou suivant dans la liste, quand on n'est pas en train de saisir.
document.addEventListener("keydown", (e) => {
  if (!["ArrowUp", "ArrowDown"].includes(e.key) || e.target.closest("input, select, textarea")) return;
  const rows = [...document.querySelectorAll(".side .p-row")];
  const i = rows.findIndex((r) => r.getAttribute("aria-current") === "true");
  const next = rows[i + (e.key === "ArrowDown" ? 1 : -1)];
  if (i >= 0 && next) { e.preventDefault(); next.click(); }
});
