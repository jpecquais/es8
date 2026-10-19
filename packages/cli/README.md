# es8ctl

A command line for the BOSS ES-8 Effects Switching System: read it, change
many patches at once, and write back with read-back verification. Every
command prints JSON, which makes it easy to drive from scripts and AI agents.

```sh
uv tool install es8ctl
es8ctl names -p WIDI                 # the 800 patch names in ≈ 7 s
es8ctl read -p WIDI                  # the whole ES-8 to a .syx file
es8ctl transform set "ctl_func[NUM_8]=BPM" -b dump.syx -o tap.json
es8ctl apply tap.json -b dump.syx --write -p WIDI --confirm
es8ctl web                           # the web editor, locally
```

Built on es8core. Part of [es8](https://github.com/jpecquais/es8); the web editor is at https://jpecquais.github.io/es8/control/.

> Not affiliated with Roland or BOSS.
