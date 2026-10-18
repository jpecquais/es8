// es8ctl — interface web (Preact + htm, sans compilation). Textes en anglais.
// Trois zones : la liste des patchs, le patch (ou la bibliothèque, ou le
// système) au centre, les modifications en attente à droite. Toute
// modification rejoint aussitôt la colonne de droite ; rien n'est envoyé à
// l'ES-8 avant « Write ».

import { html, render, useState, useEffect, useRef, useMemo } from "./vendor/preact-htm.module.js";
import * as E from "./engine.js";
import { parseChain, moveLoop, pairUp, mixWithDry, dissolve, canMix } from "./chain.js";
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
const LABELS = Array.from({ length: 800 }, (_, i) => `${Math.floor(i / 8)}-${(i % 8) + 1}`);

const pad16 = (s) => s.slice(0, 16).padEnd(16);
const bankOf = (label) => Number(label.split("-")[0]);
const indexOf = (label) => LABELS.indexOf(label);
const labelsOfBank = (b) => [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `${b}-${n}`);
const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : /(ch|sh|s|x)$/.test(word) ? "es" : "s"}`;
const fmtTime = (iso) => new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function useStore() {
  const [state, setState] = useState(store.state);
  useEffect(() => store.subscribe(setState), []);
  return state;
}

/** Les patchs doivent être lus avant d'être copiés ou déplacés : lit les banques manquantes. */
async function ensureLoaded(labels) {
  const cells = store.state.grid ? store.state.grid.cells : [];
  const missing = labels.filter((l) => (cells[indexOf(l)] || {}).missing);
  if (!missing.length) return true;
  if (!E.hasDevice()) { toast(`Read these patches from the ES-8 first: ${missing.slice(0, 6).join(", ")}…`, "error"); return false; }
  const banks = [...new Set(missing.map(bankOf))];
  return E.readSome(banks.flatMap(labelsOfBank), plural(banks.length, "bank"), true);
}

/** Déplace un patch avant ou après un autre ; les patchs entre les deux se décalent d'une place. */
async function movePatch(src, target, after) {
  const i = indexOf(src);
  let j = indexOf(target) + (after ? 1 : 0);
  if (j > i) j -= 1;
  if (i === j || i < 0) return;
  const lo = Math.min(i, j), hi = Math.max(i, j);
  if (!(await ensureLoaded(LABELS.slice(lo, hi + 1)))) return;
  const order = range(lo, hi);
  order.splice(i - lo, 1);
  order.splice(j - lo, 0, i);
  const pairs = order.map((from, k) => [LABELS[from], LABELS[lo + k]]).filter(([a, b]) => a !== b);
  if (mutate("stage_copy", JSON.stringify(pairs))) {
    toast(`${src} moved to ${LABELS[j]}; ${plural(pairs.length - 1, "patch")} shifted by one.`, "ok", 4000);
  }
}

async function exchangePatches(a, b) {
  if (!a || a === b || !(await ensureLoaded([a, b]))) return;
  if (mutate("stage_copy", JSON.stringify([[a, b], [b, a]]))) toast(`${a} ↔ ${b} swapped.`, "ok", 3000);
}

/** Glisser-déposer de patchs : au centre d'une case = échanger, sur un bord = déplacer. */
function patchDropProps(label, vertical) {
  const zone = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const pos = vertical ? (e.clientY - r.top) / r.height : (e.clientX - r.left) / r.width;
    return pos < 0.25 ? "before" : pos > 0.75 ? "after" : "swap";
  };
  const clear = (el) => el.classList.remove("drop-before", "drop-after", "drop-swap");
  return {
    draggable: true,
    onDragStart: (e) => { e.dataTransfer.setData("application/x-es8-patch", label); e.dataTransfer.effectAllowed = "move"; },
    onDragOver: (e) => {
      if (!e.dataTransfer.types.includes("application/x-es8-patch")) return;
      e.preventDefault();
      clear(e.currentTarget);
      e.currentTarget.classList.add(`drop-${zone(e)}`);
    },
    onDragLeave: (e) => clear(e.currentTarget),
    onDrop: (e) => {
      const src = e.dataTransfer.getData("application/x-es8-patch");
      if (!src) return;
      e.preventDefault();
      clear(e.currentTarget);
      const z = zone(e);
      if (z === "swap") exchangePatches(src, label);
      else movePatch(src, label, z === "after");
    },
  };
}

// ================================================================= application

function App() {
  const s = useStore();
  const prefs = useMemo(E.loadPrefs, []);
  const [view, setView] = useState(prefs.view || "patch");
  const [sel, setSel] = useState(prefs.sel || "0-1");
  const [libSel, setLibSel] = useState([]);
  useEffect(() => E.savePrefs({ view, sel }), [view, sel]);
  // Le patch actif sur l'ES-8 devient le patch affiché à la connexion.
  const lastCurrent = useRef(null);
  useEffect(() => {
    const cur = s.grid && s.grid.current;
    if (s.synced && cur && cur !== lastCurrent.current) { lastCurrent.current = cur; setSel(cur); }
  }, [s.synced, s.grid && s.grid.current]);

  const D = useMemo(() => (s.names ? makeDescriber(s.names) : null), [s.names]);
  const open = (label) => { setSel(label); setView("patch"); };

  if (!s.ready) {
    return html`<div class="splash">
      <span class="logo">es8ctl</span>
      ${s.bootError ? html`<p class="error">The engine could not load: ${s.bootError}</p>`
        : html`<p>Loading the Python engine…</p><div class="spinner"></div>`}
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
        <span>${s.toast.text}</span><button class="x" onClick=${() => store.set({ toast: null })} aria-label="Dismiss">×</button>
      </div>` : null}
    </div>`;
}

// ================================================================= barre du haut

function TopBar({ s, view, setView }) {
  const tabs = [["patch", "Patch"], ["library", "Library"], ["system", "System"]];
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
      ${E.hasDevice() && !s.synced && !s.busy ? html`<button class="btn primary" onClick=${E.sync}>Connect to the ES-8</button>` : null}
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
  let state = "off", text = "No MIDI port";
  if (s.midi === "unsupported") text = "Web MIDI unavailable";
  else if (s.midi === "denied") text = "MIDI access denied";
  else if (device) { state = s.synced ? "on" : "idle"; text = E.portName(s.out); }
  let source = "";
  if (s.fileName) source = s.fileName;
  else if (s.synced) source = "connected";
  else if (g && g.source === "cache") source = `last read ${fmtTime(g.cached_at)}`;
  return html`
    <div class="conn" ref=${ref}>
      <button class="pill ${state}" onClick=${() => setOpen(!open)} aria-expanded=${open}>
        <span class="dot"></span><span>${text}</span>${source ? html`<span class="src">· ${source}</span>` : null}
      </button>
      ${open ? html`<div class="pop">
        ${s.midi === "ok" ? html`
          <label>Output to the ES-8
            <select value=${s.out} onChange=${(e) => E.choosePorts(e.target.value, s.in)}>
              ${s.outputs.map((p) => html`<option value=${p.id}>${p.name}</option>`)}
            </select></label>
          <label>Input from the ES-8
            <select value=${s.in} onChange=${(e) => E.choosePorts(s.out, e.target.value)}>
              ${s.inputs.map((p) => html`<option value=${p.id}>${p.name}</option>`)}
            </select></label>`
        : html`<p class="muted">${s.midi === "unsupported"
            ? "This browser has no Web MIDI: use Chrome, Edge or Opera. .syx files still work."
            : s.midi === "denied" ? "Allow MIDI access (with SysEx) in the site settings, then reload the page."
            : "Looking for MIDI ports…"}</p>`}
        <div class="row2">
          <button class="btn primary" disabled=${!device || s.busy} onClick=${() => { setOpen(false); E.sync(); }}>Connect <small>≈ 10 s</small></button>
          <button class="btn" disabled=${!device || s.busy} onClick=${() => { setOpen(false); E.readDevice(); }}>Read everything <small>≈ 2 min 30</small></button>
        </div>
        <div class="files">
          <b>Files</b>
          <div class="row2">
            <label class="btn" title="Its differences with the ES-8 become pending changes">Import .syx / .bel<input type="file" accept=".syx,.bel" hidden
              onChange=${(e) => { e.target.files[0] && E.importFile(e.target.files[0]); e.target.value = ""; setOpen(false); }} /></label>
            <label class="btn" title="Browse a file instead of the ES-8">Open .syx<input type="file" accept=".syx" hidden
              onChange=${(e) => { e.target.files[0] && E.openFile(e.target.files[0]); e.target.value = ""; setOpen(false); }} /></label>
          </div>
          <div class="row2">
            <button class="btn" disabled=${!s.grid} onClick=${() => E.download(E.currentSyx(), `es8_${E.stamp()}.syx`)}>Export .syx</button>
            <button class="btn" disabled=${!s.grid} onClick=${() => {
              try { E.download(E.currentBel(), `es8_${E.stamp()}.bel`, "application/json"); }
              catch (err) { toast(`Export needs the whole ES-8 read first (${String(err).split("\n").pop()})`, "error"); }
            }}>Export .bel</button>
          </div>
        </div>
        <div class="backups">
          <b>Automatic backups</b>
          <small class="muted">Taken before every write and kept in this browser (last 5).</small>
          ${s.backups.length ? s.backups.map((b) => html`
            <button class="link" onClick=${() => E.downloadBackup(b)}>${fmtTime(b.date)}</button>`)
            : html`<small class="muted">None yet.</small>`}
        </div>
      </div>` : null}
    </div>`;
}

function Welcome({ s }) {
  const device = E.hasDevice();
  return html`
    <div class="welcome">
      <h1>A free editor for the ES-8</h1>
      <p>Connect to load your patch names and settings (about 10 seconds). Each patch is then read when you open it.</p>
      <ol>
        <li>Connect the ES-8 MIDI IN and OUT to the computer (USB MIDI interface or WIDI).</li>
        <li>Leave the ES-8 on its play screen: on the Bulk Dump screen it ignores incoming data.</li>
        <li>Check the ports in the menu at the top right, then connect.</li>
      </ol>
      <div class="row2">
        <button class="btn primary" disabled=${!device || s.busy} onClick=${E.sync}>Connect to the ES-8</button>
        <label class="btn">Open a .syx file<input type="file" accept=".syx" hidden
          onChange=${(e) => e.target.files[0] && E.openFile(e.target.files[0])} /></label>
      </div>
      ${!device ? html`<p class="muted">${s.midi === "ok" ? "No MIDI port selected." : "Web MIDI is not available here: only .syx files can be opened."}</p>` : null}
    </div>`;
}

// ================================================================= liste des patchs

/** Banques à afficher et plages de banques repliées (aucun patch nommé). */
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

const cellName = (c) => (c.name === undefined ? "not read" : c.name || "(no name)");

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

  if (!s.grid) return html`<aside class="side"><p class="muted pad">No patches loaded.</p></aside>`;
  const f = filter.trim().toUpperCase();
  const cellRow = (c) => html`
    <button class="p-row ${c.unnamed ? "unnamed" : ""} ${c.pending ? "dirty" : ""} ${c.stale ? "stale" : ""} ${c.missing ? "missing" : ""}"
      aria-current=${view === "patch" && c.patch === sel} onClick=${() => onOpen(c.patch)}
      title=${c.missing ? `${c.patch} · read when opened` : `${c.patch} · ${c.chain} · ${c.bpm} BPM${c.stale ? " · may be out of date" : ""} · drag to move or swap`}
      ...${c.missing ? {} : patchDropProps(c.patch, true)}>
      <span class="n">${c.patch}</span>
      <span class="nm">${cellName(c)}</span>
      ${s.grid.current === c.patch ? html`<span class="cur" title="Active on the ES-8">●</span>` : html`<span class="mark"></span>`}
    </button>`;

  let body;
  if (f) {
    const hits = s.grid.cells.filter((c) => (c.name || "").toUpperCase().includes(f));
    body = hits.length ? hits.map(cellRow) : html`<p class="muted pad">No patch name contains "${filter}".</p>`;
  } else {
    body = rows.map((r) => r.fold
      ? html`<button class="fold" onClick=${() => setUnfolded(new Set([...unfolded, ...range(r.from, r.to)]))}>
          ${r.from === r.to ? `Bank ${r.from}` : `Banks ${r.from}–${r.to}`} · unnamed patches</button>`
      : html`<div class="bank">
          <div class="bank-h"><span>Bank ${r.bank}</span>
            ${device ? html`<button class="link" disabled=${s.busy} title="Read the 8 patches again (≈ 2 s)"
              onClick=${() => E.readSome(labelsOfBank(r.bank), `bank ${r.bank}`)}>Re-read</button>` : null}</div>
          ${r.cells.map(cellRow)}
        </div>`);
  }
  return html`
    <aside class="side">
      <div class="search"><input type="search" placeholder="Search patches…" value=${filter}
        onInput=${(e) => setFilter(e.target.value)} aria-label="Search patches" /></div>
      <nav class="list" ref=${listRef}>${body}</nav>
    </aside>`;
}

// ================================================================= patch

const autoRead = new Set(); // banques déjà lues automatiquement pendant cette session

function PatchView({ s, D, sel }) {
  const cell = s.grid.cells[indexOf(sel)] || {};
  // Ouvrir un patch non lu (ou peut-être ancien) lit sa banque, comme l'éditeur officiel.
  useEffect(() => {
    const bank = bankOf(sel);
    if ((cell.missing || cell.stale) && s.synced && E.hasDevice() && !s.busy && !autoRead.has(bank)) {
      autoRead.add(bank); // une tentative par banque et par session : pas de boucle si l'ES-8 ne répond pas
      E.readSome(labelsOfBank(bank), `bank ${bank}`, true);
    }
  }, [sel, s.synced, s.busy]);
  const d = useMemo(() => call("patch_detail", sel), [sel, s.summary, s.grid]);
  const N = s.names;
  const [openSw, setOpenSw] = useState(null);
  const [openAssign, setOpenAssign] = useState(null);
  if (d.missing) {
    return html`<div class="pad"><h2>${sel} ${cell.name ? html`<span class="muted">${cell.name}</span>` : null}</h2>
      <p class="muted">${s.busy ? "Reading this patch…" : "This patch has not been read yet."}</p>
      ${E.hasDevice() && !s.busy ? html`<button class="btn" onClick=${() => E.readSome(labelsOfBank(bankOf(sel)), `bank ${bankOf(sel)}`)}>Read it</button>` : null}</div>`;
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
  const isDirty = Object.keys(d.pending).length > 0;
  const ctx = { d, f, N, D, stage, setAt, dirty, sel };
  const bpmRange = N.patch_ranges.master_bpm;

  return html`
    <div class="patch">
      <div class="p-head">
        <span class="num">${sel}</span>
        <input class="p-name ${dirty("name") ? "dirty" : ""}" maxlength="16" value=${f.name.trimEnd()} spellcheck="false"
          aria-label="Patch name" onChange=${(e) => stage({ name: pad16(e.target.value) })} />
        <label class="mini ${dirty("master_bpm") ? "dirty" : ""}">Tempo
          <input type="number" min=${bpmRange[0]} max=${bpmRange[1]} value=${f.master_bpm}
            onChange=${(e) => stage({ master_bpm: Number(e.target.value) })} /></label>
        <span class="grow"></span>
        <span class="fresh">
          ${s.grid.current === sel ? html`<span class="badge">active on the ES-8</span>`
            : E.hasDevice() ? html`<button class="btn" disabled=${s.busy} onClick=${() => E.play(sel)} title="Recall this patch on the ES-8">▶ Play on ES-8</button>` : null}
          ${cell.stale ? html`<span title="Shown from the last read kept by this browser">may be out of date</span>` : null}
          ${E.hasDevice() ? html`<button class="link" disabled=${s.busy} onClick=${() => E.readSome([sel], `patch ${sel}`)}>Re-read</button>` : null}
          ${isDirty ? html`<button class="link" onClick=${() => mutate("discard", sel)}>Discard changes to this patch</button>` : null}
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
  input_select: "Input", input_buffer: "Input buffer", output_select: "Output", output_buffer: "Output buffer",
  output_gain: "Output gain", mixer_mode: "Mixer", mixer_gain1: "Mixer gain 1", mixer_gain2: "Mixer gain 2",
};

function Chain({ d, f, N, stage, setAt, dirty }) {
  const [io, setIo] = useState(false);
  const [menu, setMenu] = useState(null); // { loop, top } : menu d'une loop
  const text = d.chain;
  const items = useMemo(() => parseChain(text), [text]);
  const loopIndex = (l) => (l === "V" ? 8 : Number(l) - 1);
  const setChain = (t) => { setMenu(null); if (t !== text) stage({ loop_chain: t }); };
  const mixersFree = d.mixers < 2;

  const clearDrop = (el) => el.classList.remove("drop-l", "drop-r", "drop");
  const drop = (e, target) => {
    e.preventDefault();
    clearDrop(e.currentTarget);
    if (dragged) setChain(moveLoop(text, dragged, target));
    dragged = null;
  };
  // La chaîne est dessinée entrée à gauche : la moitié gauche d'une loop = après elle dans la liste.
  const side = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    return e.clientX < r.left + r.width / 2 ? "l" : "r";
  };
  const dropZone = (target) => ({
    onDragOver: (e) => { e.preventDefault(); e.currentTarget.classList.add("drop"); },
    onDragLeave: (e) => clearDrop(e.currentTarget),
    onDrop: (e) => drop(e, target),
  });

  const loopBox = (l, top) => {
    const i = loopIndex(l), on = Boolean(f.loop_sw[i]), co = Boolean(f.carry_over_loop[i]);
    return html`
      <div class="loop ${on ? "on" : ""} ${dirty("loop_sw", i) || dirty("carry_over_loop", i) ? "dirty" : ""}"
        draggable="true" role="button" tabindex="0"
        title=${`${N.loop_labels[N.loops[i]]} · click: turn ${on ? "off" : "on"} · drag: move · right-click: more`}
        onClick=${(e) => !e.target.closest(".co") && setAt("loop_sw", i, on ? 0 : 1)}
        onContextMenu=${(e) => { e.preventDefault(); setMenu({ loop: l, top }); }}
        onKeyDown=${(e) => (e.key === " " || e.key === "Enter") && (e.preventDefault(), setAt("loop_sw", i, on ? 0 : 1))}
        onDragStart=${(e) => { dragged = l; setMenu(null); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", l); }}
        onDragEnd=${() => { dragged = null; }}
        onDragOver=${(e) => { e.preventDefault(); const k = side(e); e.currentTarget.classList.toggle("drop-l", k === "l"); e.currentTarget.classList.toggle("drop-r", k === "r"); }}
        onDragLeave=${(e) => clearDrop(e.currentTarget)}
        onDrop=${(e) => drop(e, side(e) === "l" ? { after: l } : { before: l })}>
        <span class="lbl">${l}</span><span class="led"></span>
        <button class="co ${co ? "on" : ""}" title=${co ? "Carry-over on: the loop keeps its state when changing patch"
          : `Carry-over: keep this loop's state when changing patch${mixersFree ? "" : " (no mixer left)"}`}
          onClick=${() => setAt("carry_over_loop", i, co ? 0 : 1)}>CO</button>
      </div>`;
  };

  // Liste dans l'ordre des données ; la ligne est inversée par le CSS (entrée à gauche).
  const top = items.map((it, k) => {
    const next = items[k + 1];
    const pair = it.loop && next && next.loop && canMix(text) && mixersFree
      ? html`<button class="pair" title="Mix these two loops in parallel" onClick=${() => setChain(pairUp(text, k))}>∥</button>` : null;
    const node = it.loop ? loopBox(it.loop, true) : html`
      <div class="par ${it.par === "[" ? "separate" : "mix"}">
        <span class="kind">${it.par === "[" ? "SEPARATE" : "MIX"}</span>
        <button class="unpar" title="Back to a single line" onClick=${() => setChain(dissolve(text, k))}>×</button>
        ${it.lanes.map((lane, j) => html`<div class="lane">
          ${lane.length ? lane.map((x, m) => html`${loopBox(x.loop, false)}${m + 1 < lane.length ? html`<span class="wire"></span>` : null}`)
            : html`<span class="dry" ...${dropZone({ lane: [[], k, j] })}>dry</span>`}
        </div>`)}
      </div>`;
    return html`${node}${next ? html`<span class="wire">${pair}</span>` : null}`;
  });

  const v = N.patch_values;
  const m = menu && loopIndex(menu.loop);
  return html`
    <section class="sect">
      <div class="sect-h"><h4>Chain</h4>
        <span class="hint">Click: on/off · drag: move · ∥ between two loops: mix in parallel · right-click: more · CO: carry-over</span>
        <span class="grow"></span>
        <span class="mixers ${d.mixers >= 2 ? "full" : ""}" title="The ES-8 has 2 mixers, shared by MIX blocks and carry-over loops">
          Mixers ${d.mixers} / 2</span></div>
      <div class="chain ${dirty("loop_position") ? "dirty" : ""}">
        <button class="jack" onClick=${() => setIo(!io)} title="Outputs and mixer · drop a loop here to put it last" ...${dropZone({ start: true })}>
          <b>OUT</b><span>${v.output_select[f.output_select]}${f.output_buffer ? " · buffer" : ""}</span></button>
        <span class="wire"></span>
        ${top}
        <span class="wire"></span>
        <button class="jack" onClick=${() => setIo(!io)} title="Input · drop a loop here to put it first" ...${dropZone({ end: true })}>
          <b>IN</b><span>${v.input_select[f.input_select]}${f.input_buffer ? " · buffer" : ""}</span></button>
      </div>
      ${menu ? html`<div class="loop-menu">
        <b>${N.loop_labels[N.loops[m]]}</b>
        <button class="link" onClick=${() => { setMenu(null); setAt("loop_sw", m, f.loop_sw[m] ? 0 : 1); }}>${f.loop_sw[m] ? "Turn off" : "Turn on"}</button>
        <button class="link" onClick=${() => { setMenu(null); setAt("carry_over_loop", m, f.carry_over_loop[m] ? 0 : 1); }}>
          ${f.carry_over_loop[m] ? "Carry-over off" : "Carry-over on"}</button>
        ${menu.top && canMix(text) && mixersFree ? html`<button class="link" onClick=${() => setChain(mixWithDry(text, menu.loop))}>Mix with the dry signal</button>` : null}
        ${!menu.top ? html`<button class="link" onClick=${() => setChain(moveLoop(text, menu.loop, { end: true }))}>Take out of the block</button>` : null}
        <button class="link muted" onClick=${() => setMenu(null)}>Close</button>
      </div>` : null}
      ${d.routing_problems.length ? html`<p class="warn">${d.routing_problems.join(" ")}</p>` : null}
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
      <span title="As shown on the ES-8 display: from the output side to the input side">ES-8 display</span>
      ${editing ? html`
        <form onSubmit=${(e) => { e.preventDefault(); onSet(value.trim().toUpperCase()); setEditing(false); }}>
          <input class="mono" value=${value} onInput=${(e) => setValue(e.target.value)} spellcheck="false" autofocus
            aria-label="Chain as shown on the ES-8 display" />
          <button class="btn">Apply</button><button type="button" class="link" onClick=${() => setEditing(false)}>Cancel</button>
        </form>`
      : html`<code>${text}</code>${original ? html`<span class="muted">was <code>${original}</code></span>` : null}
          <button class="link" onClick=${() => setEditing(true)}>Type it</button>`}
    </div>`;
}

// ----------------------------------------------------------------- pédalier

/** Assigns déclenchés par un pied : directement, ou via la fonction CTL qu'il porte. */
function slotAssigns(slot, fn, f, N) {
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

/** Ce que fait vraiment un pied : réglage du patch, ou réglage système s'il le remplace. */
function slotState(slot, d, N) {
  const f = d.f || d.fields;
  const isExp = slot.startsWith("EXP");
  const idx = isExp ? Number(slot[4]) - 1 : N.ctl_slots.indexOf(slot);
  const sys = d.system && (isExp ? d.system.exp_sw[idx] : d.system.ctl_sw[idx]) === 1;
  const fn = sys ? (isExp ? d.system.exp_func[idx] : d.system.ctl_func[idx]) : (isExp ? f.exp_func[idx] : f.ctl_func[idx]);
  return { isExp, idx, sys, fn, fnName: isExp ? null : N.ctl_functions[fn] };
}

function Board({ d, f, N, D, setAt, stage, dirty, openSw, setOpenSw, setOpenAssign }) {
  const card = (slot) => {
    const st = slotState(slot, d, N);
    const custom = !st.isExp && !st.sys && st.fn !== N.factory_ctl_func[st.idx];
    const assigns = slotAssigns(slot, st.fnName, f, N);
    const fnText = st.isExp ? `Pedal: ${N.patch_values.exp_func[st.fn]}` : N.ctl_function_labels[st.fn];
    return html`
      <button class="sw ${dirty(st.isExp ? "exp_func" : "ctl_func", st.idx) ? "dirty" : ""} ${st.sys ? "sys" : ""}"
        aria-pressed=${openSw === slot} onClick=${() => setOpenSw(openSw === slot ? null : slot)}>
        <span class="slot">${st.isExp ? `EXP ${st.idx + 1}` : N.ctl_slot_labels[slot]}
          ${custom ? html`<i class="custom" title="Differs from the factory setting"></i>` : null}
          ${st.sys ? html`<i class="sys-tag" title="Set by the System settings for every patch">SYSTEM</i>` : null}</span>
        <span class="fn ${custom || st.isExp || st.sys ? "" : "default"}">${fnText}</span>
        ${assigns.map((i) => html`<span class="tag">Assign ${i + 1}: ${assignSummary(i, f, N, D)}</span>`)}
      </button>`;
  };

  let detail = null;
  if (openSw) {
    const st = slotState(openSw, d, N);
    const k = st.idx;
    const patchFn = st.isExp ? f.exp_func[k] : f.ctl_func[k];
    const patchFnName = st.isExp ? null : N.ctl_functions[patchFn];
    const assigns = slotAssigns(openSw, st.fnName, f, N);
    const free = f.assign_sw.indexOf(0);
    const source = st.isExp ? `EXP${k + 1}` : /^CTL_[1-4]$/.test(st.fnName) ? `CTL${st.fnName[4]}`
      : Object.keys(SOURCE_SLOT).find((x) => SOURCE_SLOT[x] === openSw);
    const newAssign = () => {
      const sw = [...f.assign_sw]; sw[free] = 1;
      const src = [...f.assign_source]; src[free] = N.assign_sources.indexOf(source);
      if (stage({ assign_sw: sw, assign_source: src })) setOpenAssign(free);
    };
    const usePatch = () => {
      const field = st.isExp ? "exp_sw" : "ctl_sw";
      const arr = [...d.system[field]]; arr[k] = 0;
      mutate("stage_system", JSON.stringify({ [field]: arr }));
    };
    const onOff = (field) => html`<select value=${f[field][k]} onChange=${(e) => setAt(field, k, Number(e.target.value))}>
      <option value="0">Off</option><option value="1">On</option></select>`;
    detail = html`
      <div class="sw-detail">
        ${st.sys ? html`<p class="note">This switch follows the System setting (${N.ctl_function_labels[st.fn] || N.patch_values.exp_func[st.fn]}),
          so the patch setting below has no effect. <button class="link" onClick=${usePatch}>Use this patch's setting instead</button>
          (changes the System setting for every patch).</p>` : null}
        <div class="path">
          <b>${st.isExp ? `EXP ${k + 1}` : N.ctl_slot_labels[openSw]}</b><i>does</i>
          ${st.isExp
            ? html`<select value=${patchFn} onChange=${(e) => setAt("exp_func", k, Number(e.target.value))} aria-label="Function">
                ${N.patch_values.exp_func.map((l, v) => html`<option value=${v}>${l}</option>`)}</select>`
            : html`<select value=${patchFn} onChange=${(e) => setAt("ctl_func", k, Number(e.target.value))} aria-label="Function">
                ${N.ctl_function_labels.map((l, v) => html`<option value=${v}>${l}</option>`)}</select>`}
          ${!st.isExp && /^CTL_/.test(patchFnName) ? html`
            <select value=${f.ctl_mod[k]} onChange=${(e) => setAt("ctl_mod", k, Number(e.target.value))} aria-label="Mode">
              <option value="0">Momentary</option><option value="1">Toggle</option></select>
            <i>off</i>${onOff("ctl_min")}<i>on</i>${onOff("ctl_max")}` : null}
          ${st.isExp && patchFn === 3 ? html`
            <i>from</i><input type="number" min="20" max="500" value=${f.exp_min[k]} onChange=${(e) => setAt("exp_min", k, Number(e.target.value))} aria-label="Minimum BPM" />
            <i>to</i><input type="number" min="20" max="500" value=${f.exp_max[k]} onChange=${(e) => setAt("exp_max", k, Number(e.target.value))} aria-label="Maximum BPM" /><i>BPM</i>` : null}
        </div>
        ${assigns.map((i) => html`<div class="path"><i>and triggers</i>
          <button class="link" onClick=${() => setOpenAssign(i)}>Assign ${i + 1}</button><i>:</i>
          <span>${assignSummary(i, f, N, D)} (${N.patch_values.assign_mode[f.assign_mode[i]].toLowerCase()})</span></div>`)}
        <div class="muted">
          ${!st.isExp ? `Factory setting: ${N.ctl_function_labels[N.factory_ctl_func[k]]}. ` : null}
          ${assigns.length ? null : "No assign is triggered by this switch. "}
          ${free >= 0 && source ? html`<button class="link" onClick=${newAssign}>Add an assign triggered by this switch</button>` : null}
        </div>
      </div>`;
  }

  return html`
    <section class="sect">
      <div class="sect-h"><h4>Footswitches</h4><span class="hint">Orange dot: differs from the factory setting · click to edit</span></div>
      <div class="board">
        <span class="sep">Switches</span>
        ${BOARD.flat().map(card)}
        <span class="sep">CTL inputs and expression pedals</span>
        ${INPUTS.map(card)}
      </div>
      ${detail}
    </section>`;
}

// ----------------------------------------------------------------- assigns

const ASSIGN_FIELDS = ["assign_sw", "assign_source", "assign_target", "assign_mode", "assign_target_min",
  "assign_target_max", "assign_act_range_lo", "assign_act_range_hi", "assign_target_cc_ch", "assign_target_cc_no",
  "assign_int_pedal_trigger", "assign_int_pedal_trigger_cc", "assign_int_pedal_time", "assign_int_pedal_curve",
  "assign_wave_pedal_rate", "assign_wave_pedal_form"];

function Assigns({ f, N, D, setAt, stage, dirty, open, setOpen }) {
  const active = f.assign_sw.map((on, i) => (on ? i : -1)).filter((i) => i >= 0);
  const free = f.assign_sw.indexOf(0);
  const ref = useRef();
  useEffect(() => { if (open !== null && ref.current) ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [open]);
  const add = () => { if (setAt("assign_sw", free, 1)) setOpen(free); };

  return html`
    <section class="sect" ref=${ref}>
      <div class="sect-h"><h4>Assigns</h4><span class="hint">${active.length} of 12</span></div>
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
        ${free >= 0 ? html`<button class="add" onClick=${add}>+ Add an assign (${12 - active.length} free)</button>`
          : html`<p class="muted">All 12 assigns are in use.</p>`}
      </div>
    </section>`;
}

function AssignEditor({ i, f, N, setAt, stage, dirty, onRemove }) {
  const values = N.assign_target_values[f.assign_target[i]];
  const target = N.assign_targets[f.assign_target[i]];
  const source = N.assign_sources[f.assign_source[i]];
  const numRange = target === "MASTER_BPM" ? [20, 500] : [0, 127];
  const setTarget = (t) => {
    const vals = N.assign_target_values[t];
    const bpm = N.assign_targets[t] === "MASTER_BPM";
    const tg = [...f.assign_target], lo = [...f.assign_target_min], hi = [...f.assign_target_max];
    tg[i] = t;
    lo[i] = vals ? 0 : bpm ? 60 : 0;
    hi[i] = vals ? vals.length - 1 : bpm ? 120 : 127;
    stage({ assign_target: tg, assign_target_min: lo, assign_target_max: hi });
  };
  const sel = (field, labels) => html`<select value=${f[field][i]} onChange=${(e) => setAt(field, i, Number(e.target.value))}>
    ${labels.map((l, v) => (l === undefined ? null : html`<option value=${v}>${l}</option>`))}</select>`;
  const num = (field, lo, hi, offset = 0) => html`<input type="number" min=${lo} max=${hi} value=${f[field][i] + offset}
    onChange=${(e) => setAt(field, i, Number(e.target.value) - offset)} />`;
  const val = (field) => (values ? sel(field, values) : num(field, ...numRange));
  const continuous = ["EXP1", "EXP2", "INT", "WAV", "CC"].includes(source);
  const cls = (field) => (dirty(field, i) ? "dirty" : "");
  const rates = Array.from({ length: 121 }, (_, v) => (v === 0 || (v > 13 && v < 20) ? undefined : v < 20 ? N.tempo_divisions[v] : String(v - 20)));
  return html`
    <div class="editor">
      <label class=${cls("assign_source")}>Triggered by ${sel("assign_source", N.assign_source_labels)}</label>
      <label class=${cls("assign_target")}>Acts on
        <select value=${f.assign_target[i]} onChange=${(e) => setTarget(Number(e.target.value))}>
          ${N.assign_target_labels.map((l, v) => html`<option value=${v}>${l}</option>`)}</select></label>
      <label class=${cls("assign_target_min")}>Released ${val("assign_target_min")}</label>
      <label class=${cls("assign_target_max")}>Pressed ${val("assign_target_max")}</label>
      <label class=${cls("assign_mode")}>Mode ${sel("assign_mode", N.patch_values.assign_mode)}</label>
      ${continuous ? html`
        <label class=${cls("assign_act_range_lo")}>Active range, low ${num("assign_act_range_lo", 0, 126)}</label>
        <label class=${cls("assign_act_range_hi")}>Active range, high ${num("assign_act_range_hi", 1, 127)}</label>` : null}
      ${source === "CC" ? html`<label class=${cls("assign_int_pedal_trigger_cc")}>Received CC number ${sel("assign_int_pedal_trigger_cc", N.patch_values.assign_int_pedal_trigger_cc)}</label>` : null}
      ${source === "INT" ? html`
        <label class=${cls("assign_int_pedal_trigger")}>Pedal starts on ${sel("assign_int_pedal_trigger", N.patch_values.assign_int_pedal_trigger)}</label>
        ${N.patch_values.assign_int_pedal_trigger[f.assign_int_pedal_trigger[i]] === "MIDI CC"
          ? html`<label class=${cls("assign_int_pedal_trigger_cc")}>Trigger CC ${sel("assign_int_pedal_trigger_cc", N.patch_values.assign_int_pedal_trigger_cc)}</label>` : null}
        <label class=${cls("assign_int_pedal_time")}>Pedal time ${num("assign_int_pedal_time", 0, 100)}</label>
        <label class=${cls("assign_int_pedal_curve")}>Pedal curve ${sel("assign_int_pedal_curve", N.patch_values.assign_int_pedal_curve)}</label>` : null}
      ${source === "WAV" ? html`
        <label class=${cls("assign_wave_pedal_rate")}>Wave rate ${sel("assign_wave_pedal_rate", rates)}</label>
        <label class=${cls("assign_wave_pedal_form")}>Wave form ${sel("assign_wave_pedal_form", N.patch_values.assign_wave_pedal_form)}</label>` : null}
      ${target === "MIDI" ? html`
        <label class=${cls("assign_target_cc_ch")}>MIDI channel ${num("assign_target_cc_ch", 1, 16, 1)}</label>
        <label class=${cls("assign_target_cc_no")}>CC number ${num("assign_target_cc_no", 0, 127)}</label>` : null}
      <button class="link danger" onClick=${onRemove}>Turn this assign off</button>
    </div>`;
}

// ----------------------------------------------------------------- MIDI

const MIDI_FIELDS = ["midi_tx_ch", "midi_pc", "midi_pc_bank_msb", "midi_pc_bank_lsb", "midi_ctl1_cc", "midi_ctl1_cc_val", "midi_ctl2_cc", "midi_ctl2_cc_val", "midi_transmit"];

function Midi({ f, N, setAt, dirty }) {
  const [open, setOpen] = useState(null);
  const used = f.midi_tx_ch.map((ch, i) => (ch ? i : -1)).filter((i) => i >= 0);
  const free = f.midi_tx_ch.indexOf(0);
  const v = N.patch_values;
  const summary = (i) => [
    f.midi_pc[i] ? `PC ${v.midi_pc[f.midi_pc[i]]}` : null,
    f.midi_pc_bank_msb[i] || f.midi_pc_bank_lsb[i] ? `bank ${v.midi_pc_bank_msb[f.midi_pc_bank_msb[i]]} / ${v.midi_pc_bank_lsb[f.midi_pc_bank_lsb[i]]}` : null,
    f.midi_ctl1_cc[i] ? `${v.midi_ctl1_cc[f.midi_ctl1_cc[i]]} = ${f.midi_ctl1_cc_val[i]}` : null,
    f.midi_ctl2_cc[i] ? `${v.midi_ctl2_cc[f.midi_ctl2_cc[i]]} = ${f.midi_ctl2_cc_val[i]}` : null,
    f.midi_transmit[i] ? "sent manually" : null,
  ].filter(Boolean).join(" · ") || "nothing sent";
  const sel = (field, i) => html`<select value=${f[field][i]} onChange=${(e) => setAt(field, i, Number(e.target.value))}>
    ${v[field].map((l, x) => html`<option value=${x}>${l}</option>`)}</select>`;
  const num = (field, i) => html`<input type="number" min="0" max="127" value=${f[field][i]} aria-label="Value"
    onChange=${(e) => setAt(field, i, Number(e.target.value))} />`;
  return html`
    <section class="sect">
      <div class="sect-h"><h4>MIDI sent on patch call</h4><span class="hint">${used.length} of 8</span></div>
      <div class="rows">
        ${used.map((i) => html`
          <div class="item ${open === i ? "open" : ""} ${MIDI_FIELDS.some((k) => dirty(k, i)) ? "dirty" : ""}">
            <button class="item-h" onClick=${() => setOpen(open === i ? null : i)}>
              <span class="k">Ch ${v.midi_tx_ch[f.midi_tx_ch[i]]}</span><span>${summary(i)}</span></button>
            ${open === i ? html`<div class="editor">
              <label>Channel ${sel("midi_tx_ch", i)}</label>
              <label>Program change ${sel("midi_pc", i)}</label>
              <label>Bank MSB ${sel("midi_pc_bank_msb", i)}</label>
              <label>Bank LSB ${sel("midi_pc_bank_lsb", i)}</label>
              <label>CC 1 <span class="pair-in">${sel("midi_ctl1_cc", i)}${num("midi_ctl1_cc_val", i)}</span></label>
              <label>CC 2 <span class="pair-in">${sel("midi_ctl2_cc", i)}${num("midi_ctl2_cc_val", i)}</span></label>
              <label>Send ${sel("midi_transmit", i)}</label>
              <button class="link danger" onClick=${() => { setAt("midi_tx_ch", i, 0); setOpen(null); }}>Remove this message</button>
            </div>` : null}
          </div>`)}
        ${free >= 0 ? html`<button class="add" onClick=${() => { if (setAt("midi_tx_ch", free, 1)) setOpen(free); }}>
          + Add a message (${8 - used.length} free)</button>` : null}
      </div>
    </section>`;
}

// ----------------------------------------------------------------- réglages avancés

function Pick({ label, value, options, dirty, onChange }) {
  return html`<label class="pick ${dirty ? "dirty" : ""}">${label}
    <select value=${value} onChange=${(e) => onChange(Number(e.target.value))}>
      ${options.map((l, v) => (l === undefined ? null : html`<option value=${v}>${l}</option>`))}</select></label>`;
}

const LEDS = ["num1", "num2", "num3", "num4", "num5", "num6", "num7", "num8", "bank_d", "bank_u"];
const ledName = (k) => k.replace("num", "Number ").replace("bank_d", "Bank ▼").replace("bank_u", "Bank ▲");

function Advanced({ d, f, N, D, stage, dirty }) {
  const [raw, setRaw] = useState("");
  const v = N.patch_values;
  const types = d.system ? d.system.ext_ctl_types : [0, 0, 0, 0, 0, 0];
  const submitRaw = (e) => {
    e.preventDefault();
    let changes;
    try { changes = JSON.parse(raw); } catch (err) { toast(`Invalid JSON: ${err.message}`, "error"); return; }
    if (stage(changes)) setRaw("");
  };
  return html`
    <details class="sect adv">
      <summary>More settings: MIDI clock, LEDs, controller states on patch call, all fields</summary>
      <div class="io-edit">
        <${Pick} label="MIDI clock out" value=${f.midi_clock_out} options=${v.midi_clock_out} dirty=${dirty("midi_clock_out")}
          onChange=${(x) => stage({ midi_clock_out: x })} />
      </div>
      <div class="sect-h"><h4>LEDs on patch call</h4></div>
      <div class="toggles">
        ${LEDS.map((k) => html`<label class="toggle ${dirty(`led_${k}`) ? "dirty" : ""}">
          <input type="checkbox" checked=${Boolean(f[`led_${k}`])} onChange=${(e) => stage({ [`led_${k}`]: e.target.checked ? 1 : 0 })} />
          ${ledName(k)}</label>`)}
      </div>
      <div class="sect-h"><h4>CTL and EXP states on patch call</h4>
        <span class="hint">CTL in latch, pulse or inverted mode: off or on. In TP mode (System → External CTL type): a tempo division or a BPM.</span></div>
      <div class="io-edit">
        ${[1, 2, 3, 4, 5, 6].map((n) => {
          const k = `ctl${n}`;
          return types[n - 1] >= 3
            ? html`<label class="pick ${dirty(k) ? "dirty" : ""}">CTL ${n} (${D.value(k, f[k])})
                <input type="number" min="1" max="500" value=${f[k]} onChange=${(e) => stage({ [k]: Number(e.target.value) })} /></label>`
            : html`<${Pick} label=${`CTL ${n}`} value=${f[k]} options=${["Off", "On"]} dirty=${dirty(k)} onChange=${(x) => stage({ [k]: x })} />`;
        })}
        <${Pick} label="EXP 1" value=${f.exp1} options=${v.exp1} dirty=${dirty("exp1")} onChange=${(x) => stage({ exp1: x })} />
        <${Pick} label="EXP 2" value=${f.exp2} options=${v.exp2} dirty=${dirty("exp2")} onChange=${(x) => stage({ exp2: x })} />
      </div>
      <form class="raw" onSubmit=${submitRaw}>
        <label>Any other field, as JSON
          <textarea rows="3" spellcheck="false" value=${raw} onInput=${(e) => setRaw(e.target.value)}
            placeholder='{"assign_wave_pedal_rate": [7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7]}'></textarea></label>
        <button class="btn" disabled=${!raw.trim()}>Add to changes</button>
      </form>
      <details><summary>All fields of this patch</summary><pre>${JSON.stringify(f, null, 1)}</pre></details>
    </details>`;
}

// ================================================================= bibliothèque

let clipboard = []; // patchs copiés dans la bibliothèque (⌘/Ctrl+C)

function LibraryView({ s, libSel, setLibSel, onOpen }) {
  const [unfolded, setUnfolded] = useState(() => new Set());
  const keep = useMemo(() => (b) => unfolded.has(b), [unfolded]);
  const rows = useFolds(s.grid, keep);
  const last = useRef(null);
  const selSet = new Set(libSel);

  const click = (e, label) => {
    if (e.shiftKey && last.current) {
      const [a, b] = [indexOf(last.current), indexOf(label)].sort((x, y) => x - y);
      setLibSel([...new Set([...libSel, ...LABELS.slice(a, b + 1)])]);
    } else if (e.metaKey || e.ctrlKey) {
      setLibSel(selSet.has(label) ? libSel.filter((x) => x !== label) : [...libSel, label]);
    } else {
      setLibSel(selSet.has(label) && libSel.length === 1 ? [] : [label]);
    }
    last.current = label;
  };

  // ⌘/Ctrl + A, C, V, comme le Librarian officiel : tout choisir, copier, coller à partir du patch choisi.
  const selRef = useRef(libSel);
  selRef.current = libSel; // lu au moment de la touche : la sélection vient peut-être de changer
  useEffect(() => {
    const onKey = async (e) => {
      if (!(e.metaKey || e.ctrlKey) || e.target.closest("input, select, textarea")) return;
      const key = e.key.toLowerCase();
      const libSel = selRef.current;
      if (key === "a") { e.preventDefault(); setLibSel(store.state.grid.cells.filter((c) => !c.missing).map((c) => c.patch)); }
      else if (key === "c" && libSel.length) {
        e.preventDefault();
        clipboard = [...libSel].sort((x, y) => indexOf(x) - indexOf(y));
        toast(`${plural(clipboard.length, "patch")} copied. Select where to paste, then ⌘/Ctrl+V.`, "", 3000);
      } else if (key === "v" && clipboard.length) {
        e.preventDefault();
        if (libSel.length !== 1) { toast("Select the single patch where pasting starts.", "warn"); return; }
        const start = indexOf(libSel[0]);
        const pairs = clipboard.map((src, k) => [src, LABELS[start + k]]).filter((p) => p[1]);
        if (!(await ensureLoaded([...clipboard, ...pairs.map((p) => p[1])]))) return;
        if (mutate("stage_copy", JSON.stringify(pairs))) toast(`${plural(pairs.length, "patch")} pasted from ${pairs[0][1]}.`, "ok", 3000);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return html`
    <div class="library">
      <div class="p-head"><h2>Library</h2><span class="grow"></span>
        <span class="fresh">Click: select · Shift-click: range · ⌘/Ctrl-click: add · ⌘/Ctrl+C, V: copy, paste · double-click: open ·
          drag onto a patch: swap · drag onto its edge: move</span></div>
      <${SelectionBar} s=${s} sel=${libSel} clear=${() => setLibSel([])} onOpen=${onOpen} />
      <div class="lib">
        ${rows.map((r) => r.fold
          ? html`<button class="fold" onClick=${() => setUnfolded(new Set([...unfolded, ...range(r.from, r.to)]))}>
              ${r.from === r.to ? `Bank ${r.from}` : `Banks ${r.from}–${r.to}`} · unnamed patches · show</button>`
          : html`<div class="lib-row">
              <button class="bn" title="Select the whole bank" onClick=${() => setLibSel(labelsOfBank(r.bank))}>${r.bank}</button>
              ${r.cells.map((c) => html`
                <button class="cell ${c.unnamed ? "unnamed" : ""} ${c.pending ? "dirty" : ""} ${c.stale ? "stale" : ""} ${c.missing ? "missing" : ""}"
                  aria-pressed=${selSet.has(c.patch)}
                  title=${c.missing ? `${c.patch} · not read yet` : `${c.patch} · ${c.chain} · ${c.bpm} BPM`}
                  onClick=${(e) => click(e, c.patch)} onDblClick=${() => onOpen(c.patch)}
                  ...${patchDropProps(c.patch, false)}>
                  <span class="n">${c.patch}</span><span class="nm">${cellName(c)}</span>
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
  const [count, setCount] = useState(8);
  const [prefix, setPrefix] = useState("");
  if (!sel.length) {
    return html`<div class="selbar"><span>Select patches to change a setting on all of them, swap loops, copy, reset or export them.
      Click a bank number to select the whole bank.</span></div>`;
  }
  const scope = sel.join(",");
  const n = plural(sel.length, "patch");
  const done = (ok, text) => ok && toast(text, "ok", 3000);
  const sorted = [...sel].sort((x, y) => indexOf(x) - indexOf(y));
  const apply = async (e) => {
    e.preventDefault();
    if (["ctl", "bpm", "swap", "raw", "copy", "variants"].includes(action) && !(await ensureLoaded(sorted))) return;
    if (action === "ctl") {
      done(mutate("transform_set", JSON.stringify([`ctl_func[${slot}]=${fn}`]), scope),
        `${N.ctl_slot_labels[slot]} → ${N.ctl_function_labels[N.ctl_functions.indexOf(fn)]} on ${n}.`);
    } else if (action === "bpm") {
      done(mutate("transform_set", JSON.stringify([`master_bpm=${bpm}`]), scope), `Tempo ${bpm} BPM on ${n}.`);
    } else if (action === "swap") {
      done(mutate("transform_swap", a, b, scope), `${N.loop_labels[a]} ↔ ${N.loop_labels[b]} swapped on ${n}.`);
    } else if (action === "copy") {
      const start = indexOf(dest.trim());
      if (start < 0) { toast(`Unknown destination "${dest}". Example: 20-1.`, "error"); return; }
      if (start + sorted.length > 800) { toast("Not enough room after the destination.", "error"); return; }
      const pairs = sorted.map((src, k) => [src, LABELS[start + k]]);
      if (!(await ensureLoaded(pairs.map((p) => p[1])))) return;
      done(mutate("stage_copy", JSON.stringify(pairs)), `${n} copied to ${pairs[0][1]}–${pairs[pairs.length - 1][1]}.`);
    } else if (action === "factory") {
      done(mutate("stage_factory", JSON.stringify(sorted)), `${n} reset to the factory patch.`);
    } else if (action === "variants") {
      const start = dest.trim();
      if (indexOf(start) < 0) { toast(`Unknown destination "${dest}". Example: 20-1.`, "error"); return; }
      if (!(await ensureLoaded(LABELS.slice(indexOf(start), indexOf(start) + Number(count))))) return;
      done(mutate("transform_variants", sorted[0], start, Number(count), 0, prefix, false),
        `${count} variants of ${sorted[0]} from ${start}, each with a different loop order.`);
    } else if (action === "export") {
      E.download(E.currentSyx(sorted), `es8_${sorted.length === 1 ? sorted[0] : "selection"}_${E.stamp()}.syx`);
    } else {
      const lines = raw.split(/[\n;]/).map((l) => l.trim()).filter(Boolean);
      if (lines.length) done(mutate("transform_set", JSON.stringify(lines), scope), `${plural(lines.length, "assignment")} on ${n}.`);
    }
  };
  const loops = N.loops.map((l) => html`<option value=${l}>${N.loop_labels[l]}</option>`);
  return html`
    <form class="selbar" onSubmit=${apply}>
      <b>${n}</b>
      <select value=${action} onChange=${(e) => setAction(e.target.value)} aria-label="Action">
        <option value="ctl">Set a footswitch function</option>
        <option value="bpm">Set the tempo</option>
        <option value="swap">Swap two loops</option>
        <option value="copy">Copy to…</option>
        ${sel.length === 1 ? html`<option value="variants">Create variants with other loop orders</option>` : null}
        <option value="factory">Reset to the factory patch</option>
        <option value="export">Export as .syx</option>
        <option value="raw">Set fields (CLI syntax)</option>
      </select>
      ${action === "ctl" ? html`
        <select value=${slot} onChange=${(e) => setSlot(e.target.value)} aria-label="Switch">
          ${N.ctl_slots.map((x) => html`<option value=${x}>${N.ctl_slot_labels[x]}</option>`)}</select>
        <span>does</span>
        <select value=${fn} onChange=${(e) => setFn(e.target.value)} aria-label="Function">
          ${N.ctl_functions.map((x, i) => html`<option value=${x}>${N.ctl_function_labels[i]}</option>`)}</select>` : null}
      ${action === "bpm" ? html`<input type="number" min="20" max="500" value=${bpm} onInput=${(e) => setBpm(Number(e.target.value))} aria-label="Tempo" /><span>BPM</span>` : null}
      ${action === "swap" ? html`<select value=${a} onChange=${(e) => setA(e.target.value)} aria-label="First loop">${loops}</select><span>↔</span>
        <select value=${b} onChange=${(e) => setB(e.target.value)} aria-label="Second loop">${loops}</select>
        <small class="muted">switches, carry-over, assigns and place in the chain</small>` : null}
      ${action === "copy" || action === "variants" ? html`<span>starting at</span><input class="short" placeholder="20-1" value=${dest}
        onInput=${(e) => setDest(e.target.value)} aria-label="Destination" />` : null}
      ${action === "variants" ? html`<input type="number" min="1" max="200" value=${count} onInput=${(e) => setCount(e.target.value)} aria-label="How many" />
        <span>variants named</span><input class="short" placeholder="name + number" value=${prefix} maxlength="14"
          onInput=${(e) => setPrefix(e.target.value)} aria-label="Name prefix" />
        <small class="muted">targets must be unnamed patches</small>` : null}
      ${action === "factory" ? html`<small class="muted">name "BOSS ES-8", chain 87654321V, all loops off</small>` : null}
      ${action === "raw" ? html`<input class="wide" placeholder="ctl_func[NUM_8]=BPM; master_bpm=120" value=${raw} onInput=${(e) => setRaw(e.target.value)}
        spellcheck="false" aria-label="Assignments" />` : null}
      <button class="btn primary">${action === "export" ? "Download" : "Add to changes"}</button>
      <span class="grow"></span>
      ${sel.length === 1 ? html`<button type="button" class="btn" onClick=${() => onOpen(sel[0])}>Open</button>` : null}
      ${E.hasDevice() ? html`<button type="button" class="btn" disabled=${s.busy} onClick=${() => E.readSome(sorted, "the selection")}>Re-read</button>` : null}
      <button type="button" class="link" onClick=${clear}>Clear selection</button>
    </form>`;
}

// ================================================================= système

const SLOT_ORDER = ["MEM_MAN", "MUTE", "BANK_D", "BANK_U", "NUM_1", "NUM_2", "NUM_3", "NUM_4", "NUM_5", "NUM_6", "NUM_7", "NUM_8",
  "CTL_IN_1", "CTL_IN_2", "CTL_IN_3", "CTL_IN_4"];

function SystemView({ s }) {
  const [tab, setTab] = useState("settings");
  const sys = useMemo(() => call("system_detail"), [s.summary, s.grid]);
  const N = s.names;
  if (!sys) {
    return html`<div class="pad"><h2>System</h2><p class="muted">The system settings have not been read.</p>
      ${E.hasDevice() ? html`<button class="btn" onClick=${() => E.readSome(["system"], "the system settings")}>Read them</button>` : null}</div>`;
  }
  const f = sys.fields;
  const set = (k, v) => mutate("stage_system", JSON.stringify({ [k]: v }));
  const setAt = (k, i, v) => { const arr = [...f[k]]; arr[i] = v; set(k, arr); };
  const dirty = (k, i) => k in sys.pending && (i === undefined || !(k in sys.original) || sys.original[k][i] !== f[k][i]);
  return html`
    <div class="system">
      <div class="p-head"><h2>System</h2>
        <nav class="subtabs">
          ${[["settings", "Settings"], ["controllers", "Controllers"], ["pcmap", "Program change map"]].map(([id, l]) => html`
            <button aria-selected=${tab === id} onClick=${() => setTab(id)}>${l}</button>`)}
        </nav>
        <span class="grow"></span>
        <span class="fresh">Settings shared by all patches
          ${E.hasDevice() ? html`<button class="link" disabled=${s.busy} onClick=${() => E.readSome(["system"], "the system settings")}>Re-read</button>` : null}
          ${Object.keys(sys.pending).length ? html`<button class="link" onClick=${() => mutate("discard", "system")}>Discard system changes</button>` : null}
        </span></div>
      ${tab === "settings" ? html`<div class="sys">
        ${N.system_groups.map(([title, fields]) => html`
          <section class="card"><h4>${title}</h4>
            ${fields.filter(([k]) => k in f).map(([k, label]) => {
              const opts = N.system_values[k];
              const [lo, hi] = N.system_ranges[k] || [0, 127];
              return html`<label class="kv ${dirty(k) ? "dirty" : ""}"><span>${label}</span>
                ${opts ? html`<select value=${f[k]} onChange=${(e) => set(k, Number(e.target.value))}>
                    ${opts.map((l, v) => html`<option value=${v}>${l}</option>`)}</select>`
                  : html`<input type="number" min=${lo} max=${hi} value=${f[k]} onChange=${(e) => set(k, Number(e.target.value))} />`}
              </label>`;
            })}
          </section>`)}
      </div>` : tab === "controllers" ? html`
        <p class="muted">Each switch takes its function from the patch, or from these System settings for every patch.</p>
        <table class="ctl-table">
          <thead><tr><th>Switch</th><th>Uses</th><th>System function</th><th>Mode</th><th>Off / on</th></tr></thead>
          <tbody>${SLOT_ORDER.map((slot) => {
            const i = N.ctl_slots.indexOf(slot);
            const isCtl = /^CTL_/.test(N.ctl_functions[f.ctl_func[i]]);
            return html`<tr>
              <td>${N.ctl_slot_labels[slot]}</td>
              <td class=${dirty("ctl_sw", i) ? "dirty" : ""}><select value=${f.ctl_sw[i]} onChange=${(e) => setAt("ctl_sw", i, Number(e.target.value))}>
                <option value="0">Patch setting</option><option value="1">System setting</option></select></td>
              <td class=${dirty("ctl_func", i) ? "dirty" : ""}><select value=${f.ctl_func[i]} disabled=${!f.ctl_sw[i]} onChange=${(e) => setAt("ctl_func", i, Number(e.target.value))}>
                ${N.ctl_function_labels.map((l, v) => html`<option value=${v}>${l}</option>`)}</select></td>
              <td>${isCtl ? html`<select value=${f.ctl_mod[i]} disabled=${!f.ctl_sw[i]} onChange=${(e) => setAt("ctl_mod", i, Number(e.target.value))}>
                <option value="0">Momentary</option><option value="1">Toggle</option></select>` : null}</td>
              <td>${isCtl ? html`<span class="pair-in">
                <select value=${f.ctl_min[i]} disabled=${!f.ctl_sw[i]} onChange=${(e) => setAt("ctl_min", i, Number(e.target.value))}><option value="0">Off</option><option value="1">On</option></select>
                <select value=${f.ctl_max[i]} disabled=${!f.ctl_sw[i]} onChange=${(e) => setAt("ctl_max", i, Number(e.target.value))}><option value="0">Off</option><option value="1">On</option></select></span>` : null}</td>
            </tr>`;
          })}
          ${[0, 1].map((i) => html`<tr>
            <td>EXP ${i + 1}</td>
            <td class=${dirty("exp_sw", i) ? "dirty" : ""}><select value=${f.exp_sw[i]} onChange=${(e) => setAt("exp_sw", i, Number(e.target.value))}>
              <option value="0">Patch setting</option><option value="1">System setting</option></select></td>
            <td class=${dirty("exp_func", i) ? "dirty" : ""}><select value=${f.exp_func[i]} disabled=${!f.exp_sw[i]} onChange=${(e) => setAt("exp_func", i, Number(e.target.value))}>
              ${N.system_values.exp_func.map((l, v) => html`<option value=${v}>${l}</option>`)}</select></td>
            <td></td>
            <td>${f.exp_func[i] === 3 ? html`<span class="pair-in">
              <input type="number" min="20" max="500" value=${f.exp_min[i]} disabled=${!f.exp_sw[i]} onChange=${(e) => setAt("exp_min", i, Number(e.target.value))} />
              <input type="number" min="20" max="500" value=${f.exp_max[i]} disabled=${!f.exp_sw[i]} onChange=${(e) => setAt("exp_max", i, Number(e.target.value))} /> BPM</span>` : null}</td>
          </tr>`)}
          </tbody>
        </table>` : html`<${PcMap} f=${f} set=${set} dirty=${dirty} />`}
    </div>`;
}

function PcMap({ f, set, dirty }) {
  const [bank, setBank] = useState(0);
  const key = `pc_map_bank${bank}_pc`;
  const values = f[key];
  const change = (pc, text) => {
    const idx = indexOf(text.trim());
    if (idx < 0) { toast(`"${text}" is not a patch number (0-1 … 99-8).`, "error"); return; }
    const arr = [...values]; arr[pc] = idx; set(key, arr);
  };
  const reset = () => set(key, values.map((_, pc) => Math.min(bank * 128 + pc, 799)));
  return html`
    <div class="pcmap">
      <p class="muted">Which patch each received program change recalls. Bank = MIDI bank select (CC 0) value.</p>
      <div class="row2">
        <label>Bank <select value=${bank} onChange=${(e) => setBank(Number(e.target.value))}>
          ${range(0, 6).map((b) => html`<option value=${b}>${b}</option>`)}</select></label>
        <button class="link" onClick=${reset}>Reset this bank to the default order</button>
      </div>
      <div class="pc-grid">
        ${values.map((patch, pc) => html`<label class="pc ${dirty(key, pc) ? "dirty" : ""}"><span>PC ${pc}</span>
          <input value=${LABELS[patch]} size="5" onChange=${(e) => change(pc, e.target.value)} aria-label=${`Patch for PC ${pc}`} /></label>`)}
      </div>
    </div>`;
}

// ================================================================= modifications en attente

const SYSTEM_ARRAY = {
  ctl_sw: "uses", ctl_func: "system function", ctl_mod: "system mode", ctl_min: "system off value", ctl_max: "system on value",
  exp_sw: "uses", exp_func: "system function", exp_min: "system minimum", exp_max: "system maximum",
};

function systemLines(c, N, D) {
  const { field, old, new: now } = c;
  if (Array.isArray(old)) {
    const out = [];
    old.forEach((v, i) => {
      if (v === now[i]) return;
      let what, from = v, to = now[i];
      const pc = field.match(/^pc_map_bank(\d)_pc$/);
      if (pc) { what = `PC map, bank ${pc[1]}, PC ${i}`; from = LABELS[v]; to = LABELS[now[i]]; }
      else {
        const who = field.startsWith("exp") ? `EXP ${i + 1}` : N.ctl_slot_labels[N.ctl_slots[i]];
        what = `${who}, ${SYSTEM_ARRAY[field] || field}`;
        if (field.endsWith("_sw")) { from = v ? "System" : "Patch"; to = now[i] ? "System" : "Patch"; }
        else if (field === "ctl_func") { from = N.ctl_function_labels[v]; to = N.ctl_function_labels[now[i]]; }
        else if (field === "exp_func") { from = N.system_values.exp_func[v]; to = N.system_values.exp_func[now[i]]; }
        else if (field === "ctl_mod") { from = v ? "Toggle" : "Momentary"; to = now[i] ? "Toggle" : "Momentary"; }
      }
      out.push({ field, index: i, what, from, to });
    });
    return out;
  }
  const entry = N.system_groups.flatMap(([, fields]) => fields).find(([k]) => k === field);
  return [{ field, index: null, what: entry ? entry[1] : field, from: D.systemValue(field, old), to: D.systemValue(field, now) }];
}

function Tray({ s, D, onOpen }) {
  const [confirm, setConfirm] = useState(null); // "write" | "discard"
  const [expanded, setExpanded] = useState(() => new Set());
  const N = s.names;
  const groups = useMemo(() => {
    if (!D) return [];
    const by = new Map();
    const fieldsOf = {};
    for (const c of s.summary.changes) {
      if (c.target !== "system" && !fieldsOf[c.target]) fieldsOf[c.target] = call("patch_detail", c.target).fields;
      const lines = c.target === "system" ? systemLines(c, N, D) : D.lines(c, fieldsOf[c.target]);
      if (!by.has(c.target)) by.set(c.target, []);
      by.get(c.target).push(...lines);
    }
    return [...by.entries()];
  }, [s.summary, D]);
  const total = groups.reduce((n, [, l]) => n + l.length, 0);
  const nameOf = (t) => (s.grid && s.grid.cells[indexOf(t)] || {}).name || "";
  const device = E.hasDevice();
  useEffect(() => { if (!total) setConfirm(null); }, [total]);

  return html`
    <aside class="tray">
      <div class="tray-h"><h4>Changes <span class="count">${total}</span></h4>
        <small>Nothing is sent to the ES-8 until you write.</small></div>
      <div class="tray-list">
        ${total ? groups.map(([target, lines]) => html`
          <div class="t-group">
            ${target === "system" ? html`<span class="gh">System</span>`
              : html`<button class="gh" onClick=${() => onOpen(target)}>${target} · ${nameOf(target)}</button>`}
            ${(expanded.has(target) ? lines : lines.slice(0, 5)).map((l) => html`
              <div class="t-item">
                <span class="what">${l.what}</span>
                <span class="diff">${l.from} → <b>${l.to}</b></span>
                <button title="Undo this change" aria-label="Undo this change"
                  onClick=${() => mutate("revert", target, l.field, l.index ?? null)}>↶</button>
              </div>`)}
            ${lines.length > 5 ? html`<button class="t-more" onClick=${() => {
              const next = new Set(expanded); next.has(target) ? next.delete(target) : next.add(target); setExpanded(next);
            }}>${expanded.has(target) ? "Show fewer" : `Show ${lines.length - 5} more`}</button>` : null}
            ${lines.length > 1 ? html`<button class="t-more" onClick=${() => mutate("discard", target)}>
              Undo all ${lines.length} for ${target === "system" ? "the system" : target}</button>` : null}
          </div>`)
        : html`<p class="empty">No changes yet. What you edit in the middle shows up here, patch by patch, with its previous value.</p>`}
      </div>
      <div class="tray-f">
        ${s.busy ? html`<div class="progress"><span>${s.busy.label} · ${s.busy.n} / ${s.busy.total}</span>
            <progress max=${s.busy.total || 1} value=${s.busy.n}></progress></div>`
        : confirm === "write" ? html`
            <p class="note">The ES-8 must be on its play screen (on the Bulk Dump screen, press EXIT). The patches are read again just
              before sending, then checked. The current state is backed up first.</p>
            <button class="btn primary" onClick=${() => { setConfirm(null); E.writePending(); }}>Confirm and write</button>
            <button class="link" onClick=${() => setConfirm(null)}>Cancel</button>`
        : confirm === "discard" ? html`
            <button class="btn danger" onClick=${() => { setConfirm(null); mutate("discard"); }}>Yes, discard everything</button>
            <button class="link" onClick=${() => setConfirm(null)}>Keep my changes</button>`
        : html`
            <button class="btn primary" disabled=${!total || !device} onClick=${() => setConfirm("write")}>Write to the ES-8</button>
            <small class="muted">${total
              ? `${plural(s.summary.frames / 2, "page")} · about ${Math.max(1, s.summary.estimated_s)} s to send, plus reading and checking.`
              : "Re-reads the target patches, sends, then checks."}${total && !device ? " Choose the MIDI ports to write." : ""}</small>
            ${total ? html`<button class="link" onClick=${() => setConfirm("discard")}>Discard all</button>` : null}`}
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
