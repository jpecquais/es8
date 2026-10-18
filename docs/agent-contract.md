# Agent contract: driving the ES-8 with `es8ctl`

For an AI agent (LLM) or a script. **The agent only uses the CLI, never MIDI
directly.** Every write goes through `es8ctl apply`, which validates,
simulates, backs up and only sends with `--write`.

## Principles

- JSON on stdout; progress and reminders on stderr.
- Predictable exit codes: `0` success, `1` a difference was found
  (`diff`, `verify`, `check`), `2` invalid input (nothing is sent),
  `3` write interrupted (partial: read the ES-8 again and check).
- Patches are named as on the ES-8 display: `0-1` … `99-8` (bank 0–99,
  number 1–8).
- Values have the same shape as in the official editor's `.bel` files
  (integer, list, or string for `name`). `transform set` also accepts
  symbolic indexes and values (`ctl_func[NUM_8]=BPM`, `loop_sw[L6]=1`).
- Loop chain in the display notation: `loop_chain`, e.g. `V8746(3//5)21`
  (`V` = volume loop, `1`–`8` = loops, `(a//b)` = MIX block,
  `[a//b]` = SEPARATE block). The notation runs from the output side to the
  input side, as on the ES-8 display.
- Chains the ES-8 cannot run are refused (exit code 2): at most 2 mixers,
  shared by MIX blocks and carry-over loops; no block inside another block;
  SEPARATE only at the output end.

## What the agent cannot do alone

- **Make sure the ES-8 listens.** After a dump started from its panel, the
  ES-8 stays on the Bulk Dump screen, where it **silently ignores**
  everything it receives. Before any write, ask the human to press EXIT
  (play screen).

Reading needs no action on the pedal: `es8ctl read` and `es8ctl names` query
it remotely.

## Typical loop

```sh
es8ctl names --port WIDI                             # find patches by name (≈ 7 s)
es8ctl read --port WIDI --patches 0-1..0-8           # current state → captures/read_*.syx
es8ctl patches captures/<dump>.syx -p 0-8            # read
es8ctl transform set "master_bpm=120" -b captures/<dump>.syx --patches 0-1..0-8 -o changes.json
es8ctl apply changes.json -b captures/<dump>.syx     # dry run: read "changes"
es8ctl apply changes.json -b captures/<dump>.syx --write --port WIDI --confirm
# --confirm reads back and resends lost pages; "confirmed": true = stored
es8ctl check changes.json captures/<new read>.syx    # 0 = everything applied
```

## Commands

| Command | Purpose | Input → output |
|---|---|---|
| `devices` | MIDI ports | → `{input_ports, output_ports}` |
| `names` | the 800 patch names (≈ 7 s) | port → `{"0-1": name, …}` |
| `read` | read the ES-8 remotely | port → `.syx` (complete or partial); exit 1 if pages are missing |
| `capture` | record a dump started from the panel | port → `.syx` + sidecar |
| `patches` | read patches | `.syx` [`-p 0-1`] → `{patches: [{patch, …fields, loop_chain}]}` |
| `system` | read the system settings | `.syx` → `{system: {…}}` |
| `diff` | compare two dumps | → bit ranges per patch |
| `transform set` / `swap-loops` / `variants` | prepare changes | `.syx` → changes JSON |
| `import-bel` / `export-bel` | official editor files | `.bel` ⇄ changes / `.syx` → `.bel` |
| `patch select` / `rename` / `copy` / `exchange` / `init` | direct action | dry run; `--write`: backup, send, read back → `confirmed` |
| `apply` | write | changes + base `.syx` → plan; `--write` sends |
| `verify` | expected dump = actual dump? | ignores the selected patch (`current_num`) |
| `check` | are changes present in a dump? | per patch: `applied`, `mismatches` |

## Changes format

```json
{
  "patches": {"0-8": {"master_bpm": 99, "name": "MY PATCH        ",
                      "loop_chain": "V8746(3//5)21"}},
  "system": {"others_lcd_contrast": 5}
}
```

Only the given fields change; every other bit (including unmapped ones) is
taken from the base dump. An unknown field or an out-of-range value gives
exit code 2 and nothing is sent.

## Safety rules (not negotiable)

1. Always start from a **fresh** read: the base must match the ES-8.
2. Always do a dry run before `--write`, and show the `changes` to the human
   for any bulk write.
3. Always check after writing (`--confirm`, or `read` + `check`). Without
   `--confirm`, exit code 0 from `apply` means "sent", not "stored".
4. Never delete `backups/` or rewrite a file in `captures/`.
