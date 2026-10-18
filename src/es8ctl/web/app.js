// es8ctl — interface web.
// Ce fichier ne fait que brancher Web MIDI et afficher. Toute la logique
// (lecture RQ1, décodage, validation, plan d'écriture, vérification) est la
// bibliothèque Python es8ctl, exécutée dans le navigateur par Pyodide.

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const LIB_DIR = "/home/pyodide/lib";
const BACKUP_KEY = "es8ctl.backups";
const CACHE_KEY = "es8ctl.state";
const MAX_BACKUPS = 5;

const $ = (id) => document.getElementById(id);
let bridge = null;
let midiAccess = null;
let grid = null;
let names = null;
let selected = null;
let busy = false;

function status(text, kind = "") {
  $("status").textContent = text;
  $("status-bar").className = kind;
}

function progress(value, max) {
  const bar = $("progress");
  bar.hidden = value === null;
  if (value !== null) { bar.max = max; bar.value = value; }
}

function setBusy(on) {
  busy = on;
  for (const id of ["btn-read", "btn-write", "btn-discard", "btn-save"]) $(id).disabled = on || $(id).dataset.off === "1";
}

const call = (fn, ...args) => JSON.parse(bridge[fn](...args));

// ---------------------------------------------------------------- démarrage

async function boot() {
  try {
    const pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
    const archive = await (await fetch("es8ctl.zip")).arrayBuffer();
    pyodide.unpackArchive(archive, "zip", { extractDir: LIB_DIR });
    pyodide.runPython(`import sys; sys.path.insert(0, "${LIB_DIR}")`);
    bridge = pyodide.pyimport("es8ctl.webapp");
    names = call("names");
    $("filter").disabled = false;
    fillLoopSelects();
    renderBackups();
    status("Moteur prêt.");
    restoreCache();
  } catch (err) {
    status(`Échec du chargement du moteur : ${err}`, "error");
    return;
  }
  await setupMidi();
}

async function setupMidi() {
  if (!navigator.requestMIDIAccess) {
    status("Ce navigateur ne gère pas Web MIDI (Chrome, Edge ou Opera requis). Mode fichier seulement.", "warn");
    return;
  }
  try {
    midiAccess = await navigator.requestMIDIAccess({ sysex: true });
  } catch (err) {
    status(`Accès MIDI refusé (${err.name}). Mode fichier seulement.`, "warn");
    return;
  }
  midiAccess.onstatechange = fillPorts;
  fillPorts();
  status("Moteur prêt. Choisissez les ports MIDI de l'ES-8.");
}

function fillPorts() {
  const fill = (select, ports) => {
    const previous = select.value;
    select.innerHTML = "";
    for (const port of ports) select.add(new Option(port.name, port.id));
    const widi = ports.find((p) => /widi/i.test(p.name));
    select.value = ports.some((p) => p.id === previous) ? previous : (widi ? widi.id : select.value);
    select.disabled = ports.length === 0;
  };
  fill($("midi-out"), [...midiAccess.outputs.values()]);
  fill($("midi-in"), [...midiAccess.inputs.values()]);
  connectPorts();
}

function connectPorts() {
  for (const input of midiAccess.inputs.values()) input.onmidimessage = null;
  const output = midiAccess.outputs.get($("midi-out").value);
  const input = midiAccess.inputs.get($("midi-in").value);
  bridge.set_sender((bytes) => {
    const data = bytes.toJs ? bytes.toJs() : bytes;
    output.send(Array.from(data));
    if (bytes.destroy) bytes.destroy();
  });
  if (input) input.onmidimessage = (event) => bridge.push(event.data);
  const ok = Boolean(output && input);
  $("btn-read").dataset.off = ok ? "0" : "1";
  $("btn-read").disabled = !ok || busy;
  refreshPending();
}

const hasDevice = () => midiAccess && $("btn-read").dataset.off === "0";

// ---------------------------------------------------------------- lecture / fichiers

async function readDevice() {
  setBusy(true);
  status("Lecture de l'appareil… (environ 2 min 30)");
  progress(0, 1616);
  try {
    const result = JSON.parse(await bridge.read_device((n, total) => progress(n, total)));
    if (result.missing_pages.length) {
      status(`Lecture incomplète : ${result.missing_pages.length} page(s) manquante(s).`, "warn");
    } else {
      status(`Appareil lu : ${result.frames} messages.`, "ok");
    }
    saveCache();
    renderAll();
  } catch (err) {
    status(`Erreur de lecture : ${err}`, "error");
  } finally {
    progress(null);
    setBusy(false);
  }
}

async function openSyx(file) {
  try {
    const result = call("load_syx", new Uint8Array(await file.arrayBuffer()));
    status(`${file.name} : ${result.patches} patchs.`, "ok");
    renderAll();
  } catch (err) {
    status(`Fichier illisible : ${err}`, "error");
  }
}

function currentSyx() {
  const proxy = bridge.syx_bytes();
  const data = proxy.toJs();
  proxy.destroy();
  return data;
}

function download(data, name) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([data], { type: "application/octet-stream" }));
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

const stamp = () => new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");

const toBase64 = (data) => {
  let binary = "";
  for (let i = 0; i < data.length; i += 8192) binary += String.fromCharCode(...data.subarray(i, i + 8192));
  return btoa(binary);
};
const fromBase64 = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));

// ---------------------------------------------------------------- dernière lecture gardée

function saveCache() {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ date: new Date().toISOString(), data: toBase64(currentSyx()) }));
  } catch { /* stockage plein : le cache est un confort, pas une sauvegarde */ }
}

function restoreCache() {
  let cached = null;
  try { cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "null"); } catch { cached = null; }
  if (!cached) return;
  try {
    bridge.load_cached(fromBase64(cached.data), cached.date);
    renderAll();
    status(`Dernier état connu (${new Date(cached.date).toLocaleString()}). ` +
      "Cliquez sur un numéro de banque pour la relire, ou « Lire l'appareil » pour tout relire.", "warn");
  } catch { localStorage.removeItem(CACHE_KEY); }
}

async function readSome(labels, what) {
  if (!hasDevice() || busy) return;
  setBusy(true);
  status(`Relecture ${what}…`);
  try {
    const result = JSON.parse(await bridge.read_some(JSON.stringify(labels), (n, total) => progress(n, total)));
    if (result.missing_pages.length) status(`Relecture ${what} incomplète.`, "warn");
    else status(`${what[0].toUpperCase() + what.slice(1)} relu${labels.length > 1 ? "s" : ""}.`, "ok");
    saveCache();
  } catch (err) {
    status(`Erreur de relecture : ${err}`, "error");
  } finally {
    progress(null);
    setBusy(false);
    renderAll();
  }
}

// ---------------------------------------------------------------- sauvegardes (navigateur)

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
  renderBackups();
}

function renderBackups() {
  const list = loadBackups();
  const root = $("backup-list");
  root.innerHTML = list.length ? "" : `<li class="muted">Aucune sauvegarde.</li>`;
  for (const item of list) {
    const li = document.createElement("li");
    const link = document.createElement("a");
    link.href = "#";
    link.textContent = new Date(item.date).toLocaleString();
    link.onclick = (e) => {
      e.preventDefault();
      download(fromBase64(item.data), `backup_${item.date.slice(0, 19).replace(/[-:T]/g, "")}.syx`);
    };
    li.appendChild(link);
    root.appendChild(li);
  }
  $("backup-count").textContent = list.length;
}

// ---------------------------------------------------------------- modifications en attente

function refreshPending() {
  if (!bridge || !grid) return;
  const summary = call("pending_summary");
  const count = summary.patches.length + (summary.system ? 1 : 0);
  $("pending-bar").hidden = count === 0;
  $("pending-text").textContent =
    `${count} élément(s) modifié(s) · ${summary.frames} messages · environ ${summary.estimated_s} s d'écriture`;
  $("btn-write").dataset.off = hasDevice() && count ? "0" : "1";
  $("btn-write").disabled = busy || $("btn-write").dataset.off === "1";
  $("btn-discard").dataset.off = count ? "0" : "1";
  $("btn-discard").disabled = busy || !count;
  $("pending-list").innerHTML = summary.changes.map(describeChange).join("");
}

function describeChange(c) {
  let what;
  if (Array.isArray(c.old)) {
    const idx = c.old.map((v, i) => (v !== c.new[i] ? i : -1)).filter((i) => i >= 0);
    what = idx.map((i) => `[${i}] ${c.old[i]} → ${c.new[i]}`).join(", ");
  } else {
    what = `${escapeHtml(String(c.old).trimEnd())} → <strong>${escapeHtml(String(c.new).trimEnd())}</strong>`;
  }
  return `<li><span class="no">${c.target}</span> <code>${c.field}</code> ${what}</li>`;
}

function accept(resultJson, okText) {
  const result = JSON.parse(resultJson);
  if (result.error) { status(result.error, "error"); return false; }
  status(okText, "ok");
  renderAll();
  return true;
}

async function writePending() {
  const summary = call("pending_summary");
  const ok = confirm(
    `Écrire ${summary.frames / 2} page(s) sur l'ES-8 (environ ${summary.estimated_s} s) ?\n\n` +
    "Les patchs visés sont d'abord relus : vos changements s'appliquent sur leur état actuel.\n" +
    "L'ES-8 doit être sur l'écran de jeu : après un dump au panneau, appuyer sur EXIT, " +
    "sinon les pages sont ignorées. Une sauvegarde de l'état actuel est faite d'abord.");
  if (!ok) return;
  setBusy(true);
  storeBackup(currentSyx());
  const labels = { refresh: "Relecture préalable", send: "Envoi", read: "Vérification", resend: "Renvoi" };
  try {
    const result = JSON.parse(await bridge.write_pending((phase, n, total) => {
      status(`${labels[phase] || phase} : ${n} / ${total}`);
      progress(n, total);
    }));
    const drift = result.changed_on_device && result.changed_on_device.length
      ? ` Modifié sur l'appareil depuis la lecture, vos changements y ont été appliqués : ${result.changed_on_device.join(", ")}.` : "";
    if (result.error) {
      status(result.error, "error");
    } else if (result.confirmed) {
      status((result.note || `Écriture confirmée par relecture (${result.frames / 2} page(s), ` +
        `${result.history.length} tour(s)).`) + drift, "ok");
    } else {
      status(`Non confirmé après renvois : ${result.not_confirmed.join(", ")} — toujours en attente.${drift}`, "warn");
    }
    saveCache();
  } catch (err) {
    status(`Erreur d'écriture : ${err} — re-lire l'appareil avant de continuer.`, "error");
  } finally {
    progress(null);
    setBusy(false);
    renderAll();
  }
}

// ---------------------------------------------------------------- transformations

function fillLoopSelects() {
  for (const id of ["swap-a", "swap-b"]) {
    const select = $(id);
    names.loops.forEach((loop) => select.add(new Option(loop, loop)));
  }
  $("swap-b").value = "L2";
}

function runSet() {
  const lines = $("set-assign").value.split(/[\n;]/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return;
  accept(bridge.transform_set(JSON.stringify(lines), $("set-scope").value.trim() || "all"),
    "Transformation ajoutée aux modifications.");
}

function runSwap() {
  accept(bridge.transform_swap($("swap-a").value, $("swap-b").value, $("swap-scope").value.trim() || "all"),
    `Échange ${$("swap-a").value} ↔ ${$("swap-b").value} ajouté aux modifications.`);
}

// ---------------------------------------------------------------- affichage

function renderAll() {
  renderGrid();
  if (selected) renderDetail(selected);
  refreshPending();
}

function renderGrid() {
  grid = call("bank_grid");
  $("btn-save").dataset.off = "0";
  $("btn-save").disabled = busy;
  $("transforms").hidden = false;
  $("source").textContent = {
    device: "depuis l'appareil",
    file: "depuis un fichier",
    cache: `état du ${new Date(grid.cached_at).toLocaleString()} · ${grid.fresh_patches} patch(s) relu(s)`,
  }[grid.source] || "";
  const filter = $("filter").value.trim().toLowerCase();
  const root = $("grid");
  root.className = "grid";
  root.innerHTML = "";
  for (let bank = 0; bank < 100; bank++) {
    const cells = grid.cells.slice(bank * 8, bank * 8 + 8);
    if (filter && !cells.some((c) => (c.name || "").toLowerCase().includes(filter))) continue;
    const row = document.createElement("div");
    row.className = "bank";
    const no = document.createElement("button");
    no.className = "bank-no";
    no.textContent = bank;
    no.title = hasDevice() ? `Relire la banque ${bank}` : `Banque ${bank}`;
    no.onclick = () => readSome([...Array(8).keys()].map((n) => `${bank}-${n + 1}`), `de la banque ${bank}`);
    row.appendChild(no);
    for (const cell of cells) {
      const el = document.createElement("button");
      el.className = "cell";
      if (cell.missing) el.classList.add("missing");
      if (cell.patch === grid.current) el.classList.add("current");
      if (cell.patch === selected) el.classList.add("selected");
      if (cell.pending) el.classList.add("pending");
      if (cell.stale) el.classList.add("stale");
      if (cell.name === "BOSS ES-8") el.classList.add("factory");
      if (filter && !(cell.name || "").toLowerCase().includes(filter)) el.classList.add("dim");
      el.innerHTML = `<span class="no">${cell.patch}</span>` +
        `<span class="name">${escapeHtml(cell.missing ? "—" : cell.name || "(sans nom)")}</span>`;
      el.title = cell.missing ? "Page non lue" : `${cell.chain} · ${cell.bpm} BPM`;
      el.onclick = () => { selected = cell.patch; renderGrid(); renderDetail(cell.patch); };
      row.appendChild(el);
    }
    root.appendChild(row);
  }
}

function renderDetail(label) {
  const d = call("patch_detail", label);
  const root = $("detail");
  root.className = "";
  if (d.missing) { root.innerHTML = `<p class="hint">${label} : page non lue.</p>`; return; }
  const loops = Object.entries(d.loops)
    .map(([loop, on]) => `<span class="chip ${on ? "on" : ""}">${loop}</span>`).join("");
  const ctl = d.ctl.map((c) => `<tr><td>${c.slot}</td><td>${c.function}</td></tr>`).join("");
  const assigns = d.assigns.length
    ? d.assigns.map((a) => `<tr><td>${a.n}</td><td>${a.source}</td><td>${a.target}</td><td>${a.mode}</td>` +
        `<td>${a.range[0]}–${a.range[1]}</td></tr>`).join("")
    : `<tr><td colspan="5" class="muted">Aucun assign actif</td></tr>`;
  const midi = d.midi.length
    ? d.midi.map((m) => `<li>Canal ${m.ch} : PC ${m.pc}${m.bank[0] || m.bank[1] ? ` (banque ${m.bank[0]}/${m.bank[1]})` : ""}</li>`).join("")
    : `<li class="muted">Aucun message MIDI</li>`;
  const pendingNote = Object.keys(d.pending).length
    ? `<p class="pending-note">Modifications en attente : ${Object.keys(d.pending).join(", ")}
       <button class="link" id="btn-undo-patch">annuler</button></p>` : "";
  root.innerHTML = `
    <div class="detail-head">
      <h2><span class="no">${d.patch}</span> ${escapeHtml(d.name.trimEnd() || "(sans nom)")}</h2>
      <span><button id="btn-reread" title="Relire ce patch sur l'appareil">Relire</button>
      <button id="btn-edit">Modifier</button></span>
    </div>
    ${pendingNote}
    <div class="kv"><span>Tempo</span><strong>${d.bpm} BPM</strong></div>
    <h3>Chaîne</h3>
    <div class="chain">${renderChain(d.chain)}</div>
    <h3>Loops</h3>
    <div class="chips">${loops}</div>
    ${d.carry_over.length ? `<p class="muted">Carry-over : ${d.carry_over.join(", ")}</p>` : ""}
    <h3>Assigns actifs</h3>
    <table><thead><tr><th>#</th><th>Source</th><th>Cible</th><th>Mode</th><th>Plage</th></tr></thead>
      <tbody>${assigns}</tbody></table>
    <h3>MIDI à l'appel du patch</h3>
    <ul>${midi}</ul>
    <h3>Fonctions des contrôleurs</h3>
    <table class="compact"><tbody>${ctl}</tbody></table>
    ${d.warnings.length ? `<p class="warn">${d.warnings.join("<br>")}</p>` : ""}
    <details><summary>Tous les champs</summary><pre>${escapeHtml(JSON.stringify(d.fields, null, 1))}</pre></details>`;
  $("btn-edit").onclick = () => renderEditor(d);
  $("btn-reread").disabled = !hasDevice() || busy;
  $("btn-reread").onclick = () => readSome([d.patch], `du patch ${d.patch}`);
  if ($("btn-undo-patch")) $("btn-undo-patch").onclick = () => { bridge.discard(label); renderAll(); };
}

// ---------------------------------------------------------------- édition d'un patch

function options(list, value) {
  return list.map((name, i) => `<option value="${i}"${i === value ? " selected" : ""}>${name}</option>`).join("");
}

function renderEditor(d) {
  const f = d.fields;
  const toggles = (field) => names.loops.map((loop, i) =>
    `<label class="toggle"><input type="checkbox" data-field="${field}" data-i="${i}"${f[field][i] ? " checked" : ""}>${loop}</label>`).join("");
  const ctl = names.ctl_slots.map((slot, i) =>
    `<tr><td>${slot}</td><td><select data-field="ctl_func" data-i="${i}">${options(names.ctl_functions, f.ctl_func[i])}</select></td></tr>`).join("");
  const assigns = [...Array(12).keys()].map((i) => `
    <tr>
      <td><input type="checkbox" data-field="assign_sw" data-i="${i}"${f.assign_sw[i] ? " checked" : ""}> ${i + 1}</td>
      <td><select data-field="assign_source" data-i="${i}">${options(names.assign_sources, f.assign_source[i])}</select></td>
      <td><select data-field="assign_target" data-i="${i}">${options(names.assign_targets, f.assign_target[i])}</select></td>
      <td><select data-field="assign_mode" data-i="${i}">${options(["MOM", "TGL"], f.assign_mode[i])}</select></td>
      <td><input type="number" min="0" max="511" data-field="assign_target_min" data-i="${i}" value="${f.assign_target_min[i]}"></td>
      <td><input type="number" min="0" max="511" data-field="assign_target_max" data-i="${i}" value="${f.assign_target_max[i]}"></td>
    </tr>`).join("");
  const midi = [...Array(8).keys()].map((i) => `
    <tr><td>${i + 1}</td>
      <td><input type="number" min="0" max="16" data-field="midi_tx_ch" data-i="${i}" value="${f.midi_tx_ch[i]}"></td>
      <td><input type="number" min="0" max="128" data-field="midi_pc" data-i="${i}" value="${f.midi_pc[i]}"></td>
    </tr>`).join("");
  const root = $("detail");
  root.innerHTML = `
    <div class="detail-head"><h2><span class="no">${d.patch}</span> Modifier</h2></div>
    <form id="editor">
      <label class="field">Nom <input id="ed-name" maxlength="16" value="${escapeHtml(f.name.trimEnd())}"></label>
      <label class="field">Tempo (BPM) <input id="ed-bpm" type="number" min="20" max="500" value="${f.master_bpm}"></label>
      <label class="field">Chaîne <input id="ed-chain" value="${escapeHtml(d.chain)}" spellcheck="false">
        <small>Notation de l'écran : V = volume, 1–8 = loops, (a//b) = parallèle. Ex. V8746(3//5)21</small></label>
      <h3>Loops actives</h3><div class="toggles">${toggles("loop_sw")}</div>
      <h3>Carry-over</h3><div class="toggles">${toggles("carry_over_loop")}</div>
      <h3>Assigns</h3>
      <table class="edit"><thead><tr><th>On</th><th>Source</th><th>Cible</th><th>Mode</th><th>Min</th><th>Max</th></tr></thead>
        <tbody>${assigns}</tbody></table>
      <h3>MIDI à l'appel du patch</h3>
      <table class="edit"><thead><tr><th>#</th><th>Canal (0 = off)</th><th>PC (0 = off)</th></tr></thead><tbody>${midi}</tbody></table>
      <h3>Fonctions des contrôleurs</h3>
      <table class="compact"><tbody>${ctl}</tbody></table>
      <details><summary>Autres champs (JSON)</summary>
        <textarea id="ed-raw" rows="4" spellcheck="false" placeholder='{"output_select": 1, "exp_func": [3, 2]}'></textarea>
      </details>
      <div class="actions">
        <button type="submit" class="primary">Ajouter aux modifications</button>
        <button type="button" id="ed-cancel">Annuler</button>
      </div>
    </form>`;
  $("ed-cancel").onclick = () => renderDetail(d.patch);
  $("editor").onsubmit = (e) => { e.preventDefault(); stageEditor(d); };
}

function stageEditor(d) {
  const f = d.fields;
  const changes = {};
  const name = $("ed-name").value;
  if (name.padEnd(16) !== f.name) changes.name = name.padEnd(16);
  const bpm = Number($("ed-bpm").value);
  if (bpm !== f.master_bpm) changes.master_bpm = bpm;
  const chain = $("ed-chain").value.trim();
  if (chain !== d.chain) changes.loop_chain = chain;
  for (const el of $("editor").querySelectorAll("[data-field]")) {
    const field = el.dataset.field;
    const i = Number(el.dataset.i);
    const value = el.type === "checkbox" ? (el.checked ? 1 : 0) : Number(el.value);
    if (value !== f[field][i]) {
      changes[field] = changes[field] || [...f[field]];
      changes[field][i] = value;
    }
  }
  const raw = $("ed-raw").value.trim();
  if (raw) {
    try { Object.assign(changes, JSON.parse(raw)); }
    catch (err) { status(`JSON invalide : ${err.message}`, "error"); return; }
  }
  if (!Object.keys(changes).length) { status("Aucun changement."); renderDetail(d.patch); return; }
  if (accept(bridge.stage(d.patch, JSON.stringify(changes)), `${d.patch} : ${Object.keys(changes).length} champ(s) en attente d'écriture.`)) {
    renderDetail(d.patch);
  }
}

// Notation de l'écran (« V8746(3//5)21 ») → pastilles ; parallèles en encadré.
function renderChain(text) {
  let html = "";
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "(" || c === "[") html += `<span class="par"><span class="branch">`;
    else if (c === ")" || c === "]") html += `</span></span>`;
    else if (c === "/" && text[i + 1] === "/") { html += `</span><span class="branch">`; i++; }
    else html += `<span class="chip on${c === "V" ? " vol" : ""}">${c === "V" ? "V" : "L" + c}</span>`;
  }
  return `<span class="io">IN</span>${html}<span class="io">OUT</span>`;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

// ---------------------------------------------------------------- branchements

$("btn-read").onclick = readDevice;
$("btn-save").onclick = () => download(currentSyx(), `es8_${stamp()}.syx`);
$("btn-write").onclick = writePending;
$("btn-discard").onclick = () => { if (confirm("Abandonner toutes les modifications en attente ?")) { bridge.discard(); renderAll(); } };
$("btn-toggle-pending").onclick = () => { $("pending-list").hidden = !$("pending-list").hidden; };
$("file-syx").onchange = (e) => e.target.files[0] && openSyx(e.target.files[0]);
$("midi-out").onchange = connectPorts;
$("midi-in").onchange = connectPorts;
$("filter").oninput = () => grid && renderGrid();
$("btn-set").onclick = runSet;
$("btn-swap").onclick = runSwap;

boot();
