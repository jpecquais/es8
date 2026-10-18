# es8ctl compared with the official ES-8 Editor

Compared with the official BOSS ES-8 Editor 1.0.2 for macOS: its owner's
manual, plus a reading of its source code (the editor is an HTML/JavaScript
app inside the installer). Checked on 2026-10-18.

## Features

| Feature | Official editor | es8ctl web editor |
|---|---|---|
| Connect: read the system settings and the 800 names | yes, at connection | yes, at connection (≈ 10 s) |
| Read a bank when you select it | yes | yes, when a patch is opened; each bank once per session, and again with Re-read |
| Read the current patch again (PULL) | yes | yes, on a patch or a bank (Re-read) |
| Recall a patch on the ES-8 | yes, from the patch picker | yes (▶ Play on ES-8) |
| Name, tempo | yes | yes |
| Chain order, by drag and drop | yes | yes |
| Loop on/off, carry-over | yes | yes |
| MIX (parallel) blocks, including with the dry signal | yes | yes |
| SEPARATE blocks | yes (context menu) | shown, removable, and typed in the display notation; no menu to create them |
| Mixer limit (2, shared with carry-over) | yes | yes, with a counter; also enforced by the CLI |
| Input / output / buffers / output gain / mixer mode and gains | yes | yes |
| Footswitch functions, CTL mode, CTL off/on values | yes | yes |
| EXP function, BPM range | yes | yes |
| CTL and EXP states on patch call | yes | yes (More settings) |
| 12 assigns, including internal pedal, wave pedal and received CC | yes | yes |
| 8 MIDI messages on patch call (PC, bank, 2 CC, send mode), MIDI clock | yes | yes |
| LEDs on patch call | yes | yes |
| Play option, preference, MIDI, other system settings | yes | yes |
| Panel lock | not shown | yes |
| Controllers: patch or system setting, system functions | yes | yes, and the patch view shows when the system setting overrides the patch |
| Program change map (7 banks × 128) | yes | yes |
| Librarian: swap patches by drag and drop | yes | yes |
| Librarian: insert (move with shift) | listed in the menu but "Not Supported" | yes (drag onto a patch's edge) |
| Librarian: copy / paste, multi-selection | yes | yes (⌘/Ctrl+C, V, A, or "Copy to…") |
| Librarian: rename | double-click | double-click opens the patch, the name is edited there |
| Export the whole ES-8 / a selection | yes | yes (.syx, .bel; selection as .syx) |
| Import a file | replaces everything | shows only the differences as pending changes, then writes them |
| Bulk changes (one setting on many patches, swap loops, variants) | no | yes |
| Factory reset of a patch | no (the ES-8 has it on its panel) | yes |
| Search patches by name | no | yes |
| Undo a single change | no | yes |
| Runs in the browser, nothing to install | no (Windows / older macOS only) | yes |

## Official editor problems not reproduced

- **Edits lost when changing patch.** The official editor drops unsaved edits
  as soon as another patch is selected, without warning. es8ctl keeps every
  change pending until you write or discard it.
- **No check after writing.** The official editor sends pages and only checks
  that the ES-8 answers an identity request. es8ctl reads every written page
  back and resends what did not arrive. Over Bluetooth MIDI, about 1 page in
  60 is lost on the first pass.
- **Writes based on an old read.** The official editor writes the copy it read
  at connection. es8ctl reads the target patches again just before writing and
  applies the changes on top, so edits made on the panel meanwhile are kept.
- **Swap shown wrongly.** In the official editor's code, swapping two patches
  in the librarian copies one onto the other in its own display: a temporary
  variable is never filled. The ES-8 itself is right because it receives a
  direct exchange command. es8ctl reads both patches before staging the swap.
- **System settings written silently.** The official editor writes system
  settings when you leave the system screen, without asking. In es8ctl they
  are pending changes like any other.
- **Export of a selection fills the rest with the init patch.** Importing such a
  file into the official editor overwrites every other patch with the factory
  patch. es8ctl exports only the selected pages, and importing a file only
  touches the patches it contains.
- **Chain drawn from output to input.** The official editor draws OUTPUT on the
  left and INPUT on the right. es8ctl draws the signal from input (left) to
  output (right). The ES-8 display notation is still shown as the ES-8 shows it.

## Not yet checked on the ES-8 itself

- Patches using SEPARATE, stereo loop 7/8 returns, and the mixer counts that
  depend on them: the rules come from the official editor's code.
- What the ES-8 does with half a page (if a write is cut between the two
  messages of a page). Both cases are simulated in
  `tests/test_interrupted_write.py`; the read-back check repairs either one.
