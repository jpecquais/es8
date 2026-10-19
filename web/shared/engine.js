// Commun aux applis web : Pyodide (moteur es8core), Web MIDI, stockage.
// Les applis sont servies depuis la même origine : autorisation MIDI, cache de
// l'ES-8 et sauvegardes sont partagés entre elles.
// Aucune logique ES-8 ici : lecture, décodage, validation et écriture sont
// faits par le code Python du CLI, exécuté dans le navigateur.
// Textes affichés : en anglais.

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const LIB_DIR = "/home/pyodide/lib";
const BACKUP_KEY = "es8ctl.backups";
const CACHE_KEY = "es8ctl.state";
const PREFS_KEY = "es8ctl.prefs";
const MAX_BACKUPS = 5;

// ---------------------------------------------------------------- petit magasin d'état

const listeners = new Set();
export const store = {
  state: {
    ready: false, // moteur Python chargé
    bootError: null,
    midi: "pending", // pending | unsupported | denied | ok
    outputs: [], inputs: [], out: "", in: "",
    synced: false, // système et noms lus sur l'appareil pendant cette session
    busy: null, // { label, n, total } pendant un échange avec l'appareil
    toast: null, // { text, kind }
    names: null,
    grid: null,
    summary: { changes: [], frames: 0, estimated_s: 0, patches: [] },
    fileName: null,
    backups: loadBackups(),
  },
  set(patch) {
    this.state = { ...this.state, ...patch };
    listeners.forEach((fn) => fn(this.state));
  },
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
};

let bridge = null;
let midiAccess = null;
let toastTimer = null;

export function toast(text, kind = "", ms = 6000) {
  clearTimeout(toastTimer);
  store.set({ toast: { text, kind } });
  if (ms) toastTimer = setTimeout(() => store.set({ toast: null }), ms);
}

/** Appel d'une fonction du pont Python qui rend du JSON. */
export const call = (fn, ...args) => JSON.parse(bridge[fn](...args));

/** Appel qui modifie les modifications en attente ; false et message si refusé. */
export function mutate(fn, ...args) {
  const result = call(fn, ...args);
  if (result && result.error) { toast(result.error, "error"); return false; }
  refresh();
  return result || true;
}

/** Relit l'état affiché (grille, résumé des modifications) depuis le pont. */
export function refresh() {
  if (!bridge) return;
  const grid = call("bank_grid");
  store.set({
    grid: grid.cells.some((c) => !c.missing || c.name !== undefined) ? grid : null,
    summary: call("pending_summary"),
  });
}

// ---------------------------------------------------------------- démarrage

export async function boot() {
  try {
    const pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
    const archive = await (await fetch(new URL("es8core.zip", import.meta.url))).arrayBuffer();
    pyodide.unpackArchive(archive, "zip", { extractDir: LIB_DIR });
    pyodide.runPython(`import sys; sys.path.insert(0, "${LIB_DIR}")`);
    bridge = pyodide.pyimport("es8core.webapp");
    store.set({ ready: true, names: call("names") });
    restoreCache();
  } catch (err) {
    store.set({ bootError: String(err) });
    return;
  }
  await setupMidi();
}

async function setupMidi() {
  if (!navigator.requestMIDIAccess) { store.set({ midi: "unsupported" }); return; }
  try {
    midiAccess = await navigator.requestMIDIAccess({ sysex: true });
  } catch {
    store.set({ midi: "denied" });
    return;
  }
  midiAccess.onstatechange = listPorts;
  store.set({ midi: "ok" });
  listPorts();
  // Ports déjà utilisés avec succès : on se resynchronise tout seul (≈ 10 s).
  const prefs = loadPrefs();
  if (prefs.syncedOut && prefs.syncedOut === portName(store.state.out)) sync();
}

function listPorts() {
  const outputs = [...midiAccess.outputs.values()].map((p) => ({ id: p.id, name: p.name }));
  const inputs = [...midiAccess.inputs.values()].map((p) => ({ id: p.id, name: p.name }));
  const prefs = loadPrefs();
  const pick = (ports, current, saved) => {
    if (ports.some((p) => p.id === current)) return current;
    const byName = ports.find((p) => p.name === saved);
    const widi = ports.find((p) => /widi/i.test(p.name));
    return (byName || widi || ports[0] || {}).id || "";
  };
  store.set({
    outputs, inputs,
    out: pick(outputs, store.state.out, prefs.out),
    in: pick(inputs, store.state.in, prefs.in),
  });
  connectPorts();
}

export function choosePorts(out, inp) {
  store.set({ out, in: inp, synced: false });
  savePrefs({ out: portName(out), in: portName(inp) });
  connectPorts();
}

function connectPorts() {
  if (!bridge || !midiAccess) return;
  for (const input of midiAccess.inputs.values()) input.onmidimessage = null;
  const output = midiAccess.outputs.get(store.state.out);
  const input = midiAccess.inputs.get(store.state.in);
  bridge.set_sender((bytes) => {
    const data = bytes.toJs ? bytes.toJs() : bytes;
    output.send(Array.from(data));
    if (bytes.destroy) bytes.destroy();
  });
  if (input) input.onmidimessage = (event) => bridge.push(event.data);
}

export const hasDevice = () => Boolean(midiAccess && store.state.out && store.state.in);
export const portName = (id) => ([...store.state.outputs, ...store.state.inputs].find((p) => p.id === id) || {}).name || "";

// ---------------------------------------------------------------- échanges avec l'appareil

async function withDevice(label, total, job) {
  if (!hasDevice() || store.state.busy) return null;
  store.set({ busy: { label, n: 0, total } });
  try {
    return await job((n, t, phase) => store.set({ busy: { label: phase || label, n, total: t } }));
  } catch (err) {
    toast(`Communication error: ${err}`, "error", 0);
    return null;
  } finally {
    store.set({ busy: null });
    refresh();
  }
}

/** Connexion : réglages système et 800 noms (≈ 10 s), comme l'éditeur officiel. */
export async function sync() {
  const result = await withDevice("Reading names", 816, async (progress) => {
    const sys = JSON.parse(await bridge.read_some(JSON.stringify(["system"]), (n) => progress(n, 816, "Reading system")));
    const names = JSON.parse(await bridge.read_names((n) => progress(16 + n, 816, "Reading names")));
    return { sys, names };
  });
  if (!result) return false;
  if (result.names.names < 800 || result.sys.missing_pages.length) {
    toast("The ES-8 did not answer. Check the MIDI cables or WIDI pairing, the ports, and that the ES-8 is on its play screen.", "error", 0);
    return false;
  }
  store.set({ synced: true, fileName: null });
  savePrefs({ syncedOut: portName(store.state.out) });
  saveCache();
  return true;
}

export async function readDevice() {
  const result = await withDevice("Reading the whole ES-8", 1616, async (progress) =>
    JSON.parse(await bridge.read_device((n, t) => progress(n, t))));
  if (!result) return;
  store.set({ fileName: null, synced: true });
  if (result.missing_pages.length) toast(`Read incomplete: ${result.missing_pages.length} page(s) missing.`, "warn", 0);
  else toast("ES-8 read.", "ok");
  saveCache();
}

/** Relit des patchs (« 3-1 ») et/ou « system ». */
export async function readSome(labels, what, quiet = false) {
  const result = await withDevice(`Reading ${what}`, labels.length * 2, async (progress) =>
    JSON.parse(await bridge.read_some(JSON.stringify(labels), (n, t) => progress(n, t))));
  if (!result) return false;
  if (result.missing_pages.length) toast(`Could not read all of ${what}.`, "warn");
  else if (!quiet) toast(`Read ${what}.`, "ok", 2500);
  saveCache();
  return !result.missing_pages.length;
}

/** Rappelle un patch sur l'ES-8. */
export async function play(label) {
  if (!hasDevice() || store.state.busy) return;
  await bridge.select_on_device(label);
  refresh();
}

const PHASES = { refresh: "Re-reading targets", send: "Sending", read: "Verifying", resend: "Resending" };

export async function writePending() {
  storeBackup(currentSyx());
  const result = await withDevice("Writing", 1, async (progress) =>
    JSON.parse(await bridge.write_pending((phase, n, t) => progress(n, t, PHASES[phase] || phase))));
  if (!result) return;
  const drift = result.changed_on_device && result.changed_on_device.length
    ? ` Changed on the ES-8 since the last read (your edits were applied on top): ${result.changed_on_device.join(", ")}.` : "";
  if (result.error) toast(result.error, "error", 0);
  else if (result.confirmed) toast((result.note || `Written and verified (${result.frames / 2} page(s)).`) + drift, "ok", 8000);
  else toast(`Not confirmed after resending: ${result.not_confirmed.join(", ")}. These patches stay pending.${drift}`, "warn", 0);
  saveCache();
}

// ---------------------------------------------------------------- fichiers

const kindOf = (file) => (/\.bel$/i.test(file.name) ? "bel" : "syx");

/** Ouvre un fichier pour le consulter (remplace l'état affiché, sans rien écrire). */
export async function openFile(file) {
  try {
    if (kindOf(file) === "bel") { toast("A .bel file can only be imported into the ES-8 state: use Import.", "warn"); return; }
    const result = call("load_syx", new Uint8Array(await file.arrayBuffer()));
    store.set({ fileName: file.name, grid: null, synced: false });
    refresh();
    toast(`${file.name}: ${result.patches} patches. Viewing the file, not the ES-8.`, "ok");
  } catch (err) {
    toast(`Cannot read this file: ${err}`, "error");
  }
}

/** Importe un .syx ou .bel : ses différences avec l'ES-8 deviennent des modifications en attente. */
export async function importFile(file) {
  const result = mutate("import_file", new Uint8Array(await file.arrayBuffer()), kindOf(file));
  if (!result) return;
  const skipped = result.warnings && result.warnings.length ? ` ${result.warnings.length} patch(es) skipped (not read from the ES-8 yet).` : "";
  toast(result.imported ? `${file.name}: ${result.imported} patch(es) differ and were added to the changes.${skipped}`
    : `${file.name}: nothing differs from the ES-8.${skipped}`, result.imported ? "ok" : "", 8000);
}

export function currentSyx(labels) {
  const proxy = bridge.syx_bytes(labels ? JSON.stringify(labels) : null);
  const data = proxy.toJs();
  proxy.destroy();
  return data;
}

export const currentBel = () => bridge.bel_text();

export function download(data, name, type = "application/octet-stream") {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([data], { type }));
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

export const stamp = (date = new Date()) => date.toISOString().slice(0, 19).replace(/[-:T]/g, "");

const toBase64 = (data) => {
  let binary = "";
  for (let i = 0; i < data.length; i += 8192) binary += String.fromCharCode(...data.subarray(i, i + 8192));
  return btoa(binary);
};
const fromBase64 = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));

// ---------------------------------------------------------------- stockage du navigateur

function saveCache() {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ date: new Date().toISOString(), data: toBase64(currentSyx()) }));
  } catch { /* stockage plein ou refusé : le cache est un confort */ }
}

function restoreCache() {
  let cached = null;
  try { cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "null"); } catch { cached = null; }
  if (!cached) return;
  try {
    bridge.load_cached(fromBase64(cached.data), cached.date);
    refresh();
  } catch {
    try { localStorage.removeItem(CACHE_KEY); } catch { /* rien */ }
  }
}

function loadBackups() {
  try { return JSON.parse(localStorage.getItem(BACKUP_KEY) || "[]"); } catch { return []; }
}

function storeBackup(data) {
  const list = [{ date: new Date().toISOString(), data: toBase64(data) }, ...loadBackups()].slice(0, MAX_BACKUPS);
  try {
    localStorage.setItem(BACKUP_KEY, JSON.stringify(list));
  } catch {
    download(data, `backup_${stamp()}.syx`); // stockage plein : sauvegarde téléchargée
  }
  store.set({ backups: loadBackups() });
}

export function downloadBackup(item) {
  download(fromBase64(item.data), `backup_${stamp(new Date(item.date))}.syx`);
}

export function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}"); } catch { return {}; }
}

export function savePrefs(patch) {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify({ ...loadPrefs(), ...patch })); } catch { /* rien */ }
}
