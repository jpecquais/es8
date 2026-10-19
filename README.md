# es8

Free, open-source tools for the BOSS ES-8 Effects Switching System:

- **ES8 Control**, a web editor that talks to the ES-8 from the browser over
  Web MIDI (ES8 Designer will follow);
- **es8ctl**, a command line that scripts, AI agents and you can drive, also
  available as a Docker image;
- **es8core**, the engine they share.

**Open ES8 Control: https://jpecquais.github.io/es8/control/**

They all decode, validate and write the ES-8 data with the same engine.
Every write is read back from the ES-8 and checked before it counts as done.

> Not affiliated with Roland or BOSS. "BOSS" and "ES-8" are trademarks of
> Roland Corporation, used here only to say which device this works with.

## What you need

- A BOSS ES-8 with firmware 2.x.
- A MIDI link in **both directions** between the computer and the ES-8: a USB
  MIDI interface with two cables, or a Bluetooth adapter such as a CME WIDI
  Jack (the ES-8 has no USB port).
- For the web editor: Chrome, Edge or Opera (Web MIDI with SysEx).
- For the command line: Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

Leave the ES-8 on its play screen while editing. On the Bulk Dump screen it
silently ignores everything it receives.

## ES8 Control (web editor)

Open the hosted editor at https://jpecquais.github.io/es8/control/, or run it locally:

```sh
uv sync
uv run es8ctl web          # opens http://localhost:8765/control/
```

Accept the browser's request for MIDI access with SysEx, check the ports in
the top-right menu and press **Connect**. The editor reads the system
settings and the 800 patch names in about 10 seconds. Each patch is read
when you open it (about 2 seconds per bank).

The screen has three parts: the patch list on the left, the editor in the
middle, and your pending changes on the right. Nothing is sent to the ES-8
until you press **Write**.

- **Patch**: everything is edited in place.
  - **Chain**: drawn from input to output. Click a loop to turn it on or
    off; drag it to move it; use **∥** between two loops to mix them in
    parallel; right-click a loop for more options. CO is carry-over. The
    mixer counter shows how many of the ES-8's 2 mixers the patch uses.
  - **Footswitches**: laid out like the pedal. Each switch shows its
    function, the assigns it triggers, and whether a System setting
    overrides it.
  - **Assigns** and **MIDI messages**: only the ones in use are listed.
  - **More settings**: LEDs, CTL/EXP states, any field as JSON.
- **Library**: select patches (Shift, ⌘/Ctrl). You can then:
  - set a footswitch function or the tempo;
  - swap two loops;
  - copy the patches elsewhere, or create routing variants;
  - reset them to the factory patch, or export them.

  Drag a patch onto another to swap them, or onto its edge to move it; the
  patches in between shift by one.
- **System**: play options, preferences, manual mode, MIDI, controllers
  (patch or system setting) and the program change map.
- **Changes**: grouped by patch, with the previous value, and each one can be
  undone on its own. **Write** works in four steps:
  1. it reads the target patches again, so your edits land on the ES-8's
     current state;
  2. it saves a backup in the browser;
  3. it sends only the pages that changed;
  4. it reads them back and resends anything that did not arrive.
- **Files** (top-right menu):
  - **Import** a `.syx` or `.bel` file: its differences with the ES-8
    become pending changes.
  - **Open** a `.syx` file to browse it without a pedal.
  - **Export** the whole state as `.syx` or `.bel`.

The editor refuses chains the ES-8 cannot run. It applies the same rules as
the official BOSS editor: at most 2 mixers (shared by MIX blocks and
carry-over loops), no block inside another block, and SEPARATE only at the
output end.

## es8ctl (command line)

```sh
uv tool install es8ctl     # once published; from this repository: uv sync && uv run es8ctl --help
es8ctl --help
```

All commands print JSON and are dry runs unless you pass `--write`.

```sh
es8ctl names -p WIDI                         # the 800 patch names (≈ 7 s)
es8ctl read -p WIDI                          # the whole ES-8 to a .syx (≈ 2 min 20)
es8ctl read -p WIDI --patches 0-1..0-8 --no-system

es8ctl patches captures/<dump>.syx -p 6-2    # decode patches to JSON
es8ctl system captures/<dump>.syx            # system settings and PC map

# Bulk changes: describe them, check them, then write and verify
es8ctl transform set "ctl_func[NUM_8]=BPM" -b captures/<dump>.syx -o tap.json
es8ctl transform swap-loops 6 7 -b captures/<dump>.syx -o swap.json
es8ctl transform variants 0-8 --into 10-1 -n 50 -b captures/<dump>.syx -o var.json
es8ctl apply tap.json --base captures/<dump>.syx                         # dry run
es8ctl apply tap.json --base captures/<dump>.syx --write -p WIDI --confirm

# Direct commands, each checked by reading back
es8ctl patch select 6-2 -p WIDI
es8ctl patch rename 0-8 "MY PATCH" --write -p WIDI
es8ctl patch copy 0-8 99-2 --write -p WIDI
es8ctl patch exchange 0-1 0-2 --write -p WIDI

# .bel files (librarian files of the official ES-8 Editor)
es8ctl export-bel captures/<dump>.syx -o my_es8.bel
es8ctl import-bel file.bel --base captures/<dump>.syx -o changes.json
```

`-p` takes a port name or a unique prefix of it. Changes are JSON in the same
shape as `es8ctl patches`, for example
`{"patches": {"49-1": {"name": "MY PATCH        ", "master_bpm": 99}}}`.
The chain uses the ES-8 display notation: `"loop_chain": "V8746(3//5)21"`.

Every write first saves the current state to `backups/` (never overwritten).
`--confirm` reads the written pages back and resends those that differ. Over
Bluetooth, about 1 page in 60 gets lost on the first pass.

`docs/agent-contract.md` describes how an AI agent should drive the CLI.

### Docker

```sh
docker run --rm -v "$PWD:/work" ghcr.io/jpecquais/es8-cli transform set "master_bpm=120" -b dump.syx
```

On macOS and Windows, Docker cannot reach MIDI devices: use the image for
work without the pedal (preparing changes, dry runs, file conversion), or
install the CLI with uv to talk to the ES-8. On Linux, including a Raspberry
Pi, pass the sound devices to reach the ES-8:
`docker run --rm --device /dev/snd -v "$PWD:/work" ghcr.io/jpecquais/es8-cli names -p <port>`.

## Hosting and releases

The web apps are a static site: all the work happens in the browser, so any
HTTPS host works. One site holds the home page and every app, so the apps
share the MIDI permission and the last read of the ES-8:

```
https://jpecquais.github.io/es8/            home page
https://jpecquais.github.io/es8/control/    ES8 Control
https://jpecquais.github.io/es8/designer/   ES8 Designer (later)
```

```sh
uv run es8ctl build-web --out dist/site
```

GitHub Actions workflows:

- `ci.yml` runs the tests and builds the Docker image on every push;
- `pages.yml` publishes the site on every push to `main` (turn it on once in
  **Settings → Pages → Source: GitHub Actions**);
- `release.yml` runs on a `vX.Y.Z` tag. It publishes the Docker image
  (`ghcr.io/jpecquais/es8-cli`, amd64 and arm64) and the `es8core` and `es8ctl`
  packages on PyPI. For PyPI, add this workflow once as a trusted publisher
  for each package on pypi.org.

## How it works

The ES-8 exchanges its memory as Roland bulk dump messages: 16 for the
system, 2 per patch, each holding 125 bytes of a bit-packed record. es8ctl
decodes every field (it matches the official editor's parameter database),
reads the ES-8 remotely with the official editor's request messages, and
writes pages back the same way.

Developer notes, in French:
- `docs/bulk-format.md`: format, protocol and measurements;
- `docs/sniff-editor.md`: how to record the official editor;
- `PLAN.md`: the plan and its progress.

```
packages/
  core/src/es8core/     the engine (no dependencies, also runs in Pyodide)
    codec/              Roland SysEx envelope, ES-8 bulk frames and pages
    layout.py           bit-packed fields ↔ JSON
    patch.py, system.py field maps (firmware 2)
    routing.py          loop chain ↔ display notation, hardware routing rules
    transform.py        bulk changes
    apply.py            changes → pages → frames, validation
    session.py          talking to the ES-8 (reads, verified writes), any transport
    request.py, live.py remote reads, name list, direct commands
    bel.py              .bel import/export
    webapp.py           bridge used by the web apps
    labels.py           value labels shown by the web apps
  cli/src/es8ctl/       the command line (typer, mido); Dockerfile next to it
web/
  shared/               shared by the apps: Pyodide, Web MIDI, cache, chain model, Preact
  control/              ES8 Control
site/                   home page
tests/                  tests for everything above
```

## Development

The repository is a uv workspace: one `uv sync` installs both packages in
editable mode.

```sh
uv sync
uv run pytest
uv run es8ctl web          # serves site/ and web/ live: edit and reload
```

The tests run without an ES-8, using captured dumps and simulated devices.
This includes simulated interrupted writes (`tests/test_interrupted_write.py`).

## License

AGPL-3.0-or-later, see `LICENSE`. The web apps bundle Preact (MIT) and htm (Apache-2.0),
and load Pyodide (MPL-2.0) from its CDN.
