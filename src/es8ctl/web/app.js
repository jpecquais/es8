// es8ctl — interface web.
// Ce fichier ne fait que deux choses : brancher Web MIDI et afficher.
// Toute la logique (lecture RQ1, décodage, routing) est la bibliothèque
// Python es8ctl, exécutée dans le navigateur par Pyodide (module webapp).

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const LIB_DIR = "/home/pyodide/lib";

const $ = (id) => document.getElementById(id);
let bridge = null;
let midiAccess = null;
let grid = null;
let selected = null;

function status(text, kind = "") {
  $("status").textContent = text;
  $("status-bar").className = kind;
}

function progress(value, max) {
  const bar = $("progress");
  bar.hidden = value === null;
  if (value !== null) { bar.max = max; bar.value = value; }
}

// ---------------------------------------------------------------- démarrage

async function boot() {
  try {
    const pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
    const archive = await (await fetch("es8ctl.zip")).arrayBuffer();
    pyodide.unpackArchive(archive, "zip", { extractDir: LIB_DIR });
    pyodide.runPython(`import sys; sys.path.insert(0, "${LIB_DIR}")`);
    bridge = pyodide.pyimport("es8ctl.webapp");
    $("filter").disabled = false;
    status("Moteur prêt.");
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
    for (const port of ports) {
      const option = new Option(port.name, port.id);
      select.add(option);
    }
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
  $("btn-read").disabled = !(output && input);
}

// ---------------------------------------------------------------- actions

async function readDevice() {
  $("btn-read").disabled = true;
  status("Lecture de l'appareil… (environ 2 min 30)");
  progress(0, 1616);
  try {
    const result = JSON.parse(await bridge.read_device((n, total) => progress(n, total)));
    if (result.missing_pages.length) {
      status(`Lecture incomplète : ${result.missing_pages.length} page(s) manquante(s).`, "warn");
    } else {
      status(`Appareil lu : ${result.frames} messages.`, "ok");
    }
    renderGrid();
  } catch (err) {
    status(`Erreur de lecture : ${err}`, "error");
  } finally {
    progress(null);
    $("btn-read").disabled = false;
  }
}

async function openSyx(file) {
  try {
    const data = new Uint8Array(await file.arrayBuffer());
    const result = JSON.parse(bridge.load_syx(data));
    status(`${file.name} : ${result.patches} patchs.`, "ok");
    renderGrid();
  } catch (err) {
    status(`Fichier illisible : ${err}`, "error");
  }
}

function saveSyx() {
  const proxy = bridge.syx_bytes();
  const data = proxy.toJs();
  proxy.destroy();
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([data], { type: "application/octet-stream" }));
  link.download = `es8_${stamp}.syx`;
  link.click();
  URL.revokeObjectURL(link.href);
}

// ---------------------------------------------------------------- affichage

function renderGrid() {
  grid = JSON.parse(bridge.bank_grid());
  $("btn-save").disabled = false;
  $("source").textContent = grid.source === "device" ? "depuis l'appareil" : "depuis un fichier";
  const filter = $("filter").value.trim().toLowerCase();
  const root = $("grid");
  root.className = "grid";
  root.innerHTML = "";
  for (let bank = 0; bank < 100; bank++) {
    const cells = grid.cells.slice(bank * 8, bank * 8 + 8);
    if (filter && !cells.some((c) => (c.name || "").toLowerCase().includes(filter))) continue;
    const row = document.createElement("div");
    row.className = "bank";
    row.innerHTML = `<span class="bank-no">${bank}</span>`;
    for (const cell of cells) {
      const el = document.createElement("button");
      el.className = "cell";
      if (cell.missing) el.classList.add("missing");
      if (cell.patch === grid.current) el.classList.add("current");
      if (cell.patch === selected) el.classList.add("selected");
      if (filter && !(cell.name || "").toLowerCase().includes(filter)) el.classList.add("dim");
      const factory = cell.name === "BOSS ES-8";
      if (factory) el.classList.add("factory");
      el.innerHTML = `<span class="no">${cell.patch}</span>` +
        `<span class="name">${escapeHtml(cell.missing ? "—" : cell.name || "(sans nom)")}</span>`;
      el.title = cell.missing ? "Page non lue" : `${cell.chain} · ${cell.bpm} BPM`;
      el.onclick = () => selectPatch(cell.patch);
      row.appendChild(el);
    }
    root.appendChild(row);
  }
}

function selectPatch(label) {
  selected = label;
  renderGrid();
  const d = JSON.parse(bridge.patch_detail(label));
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
  root.innerHTML = `
    <h2><span class="no">${d.patch}</span> ${escapeHtml(d.name.trimEnd() || "(sans nom)")}</h2>
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
$("btn-save").onclick = saveSyx;
$("file-syx").onchange = (e) => e.target.files[0] && openSyx(e.target.files[0]);
$("midi-out").onchange = connectPorts;
$("midi-in").onchange = connectPorts;
$("filter").oninput = () => grid && renderGrid();

boot();
