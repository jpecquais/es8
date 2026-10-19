# es8core

The engine behind the es8 tools for the BOSS ES-8 Effects Switching System.

- Decodes and encodes every patch and system field of the ES-8 bulk data
  (firmware 2), matching the official editor's parameter database.
- Converts loop chains to and from the ES-8 display notation
  (`V8746(3//5)21`) and refuses chains the ES-8 cannot run.
- Plans writes page by page, reads the ES-8 remotely, and writes with
  read-back verification, over any MIDI transport.

It has no dependencies, so it also runs in the browser through Pyodide: the
es8 web apps use it there. Install `es8core[midi]` to talk to an ES-8 from
Python with mido.

Part of [es8](https://github.com/jpecquais/es8), with the es8ctl command line and the web apps.

License: AGPL-3.0-or-later.

> Not affiliated with Roland or BOSS.
