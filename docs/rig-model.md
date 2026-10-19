# Modèle pedalboard → rig → snapshot

Couche d'édition par intention au-dessus des champs de patch : on décrit le
matériel, puis des rigs et leurs snapshots, et un compilateur produit le même
format de changements que `transform` (`{patches, system}`), consommé par
`apply` (CLI) ou `_accept` (web). Aucun nouveau chemin vers l'ES-8.

Statut : proposition (2026-10-18), rien n'est codé. Maquette d'interface :
https://claude.ai/artifact/2GHaQenYoy9vhSk1RPRMrZ

## Vocabulaire

| Terme | Ce que c'est | Sur l'ES-8 |
|---|---|---|
| **Pedalboard** | Le matériel branché : pédales dans les loops, sorties CTL, entrées, appareils MIDI | rien (fichier seulement) |
| **Rig** | Une configuration jouable : ordre des loops, programme chargé sur chaque appareil, surface | une banque (8 patchs) |
| **Snapshot** | Un état du rig : loops actives, valeurs des paramètres MIDI | un patch |
| **Surface** | Le rôle de chaque switch, partageable entre rigs | assigns, `ctl_func`, `manual_number` |
| **Destination** | Un appareil MIDI du pedalboard (Live n'en est qu'un) | slots MIDI des patchs |
| **Setlist** (plus tard) | Liste ordonnée de rigs, avec snapshot de départ | aucun stockage |

Décisions actées :

- Un rig = une banque, 8 snapshots au plus. Pas de rig sur deux banques en v1.
- Le flux va dans un sens : l'ES-8 détient l'état et pilote les destinations.
  Un changement venu d'une destination (souris dans Live) n'est pas renvoyé.
- Un rig, c'est une partie locale (loops, surface) et une partie distante
  (les PC qui chargent le bon programme sur chaque appareil). Les PC du rig
  sont recopiés dans les 8 snapshots : rappeler un snapshot depuis un autre
  rig doit charger les bons programmes.
- Les fichiers sont la vérité ; l'ES-8 est le résultat compilé.

## Fichiers

Tous en JSON, avec un champ `schema` versionné. Les références entre
fichiers sont des chemins relatifs.

### `pedalboard.json`

```json
{
  "schema": "es8ctl.pedalboard/1",
  "name": "Pedalboard principal",
  "loops": {
    "L1": {"name": "Compresseur", "kind": "dynamics"},
    "L2": {"name": "Overdrive", "kind": "drive"},
    "L3": null,
    "L8": {"name": "Pédale delay", "kind": "delay", "device": "delay"}
  },
  "ctl_out": {"CTL1": "Ampli · canal", "CTL2": "Ampli · reverb"},
  "inputs": {"EXP1": "Pédale de volume", "CTL_IN_1": "Footswitch externe A"},
  "devices": {
    "live": {
      "name": "Ableton Live",
      "channel": 1,
      "program_change": "pc",
      "repeated_pc": "ignored",
      "programs": {"crunch": {"pc": 12, "name": "Crunch Lead"}},
      "params": {
        "drive": {"name": "Drive · On", "cc": 18, "off": 0, "on": 127},
        "delay": {"name": "Delay · On", "cc": 19, "off": 0, "on": 127}
      }
    },
    "reverb": {
      "name": "Pédale reverb",
      "channel": 2,
      "program_change": "pc",
      "repeated_pc": "reloads",
      "programs": {"hall": {"pc": 5, "name": "Hall long"}},
      "params": {"freeze": {"name": "Freeze", "cc": 21, "off": 0, "on": 127}}
    }
  }
}
```

- `program_change` : `none` | `pc` | `bank_msb_pc` | `bank_lsb_pc` | `bank_msb_lsb_pc`.
- `repeated_pc` : `ignored` | `reloads` | `unknown`. Sert aux avertissements.
- Un paramètre est désigné ailleurs par `<appareil>.<param>` (`live.drive`).
- Les valeurs PC sont celles de l'appareil (0–127) ; l'encodage dans
  `midi_pc` (0–128, 0 = rien ?) est l'affaire du compilateur, à confirmer.

### `surface.json`

```json
{
  "schema": "es8ctl.surface/1",
  "name": "Lead 4 + 4",
  "switches": {
    "NUM1": {"label": "Drive", "role": "param", "param": "live.drive", "mode": "toggle"},
    "NUM4": {"label": "Freeze", "role": "param", "param": "reverb.freeze", "mode": "momentary"},
    "NUM5": {"label": "Overdrive", "role": "loop", "loop": "L2"},
    "NUM8": {"label": "Tap", "role": "tap"}
  }
}
```

Rôles : `param` (CC vers une destination), `loop`, `tap`, `es8` (fonction
native : `MEM_M`, `MUTE`…), absent = inchangé. Les switches s'appliquent au
mode manuel ; en mode patch, NUM1–8 rappellent les snapshots.

### `rigs/<nom>.json`

```json
{
  "schema": "es8ctl.rig/1",
  "name": "Crunch Lead",
  "short": "Crunch",
  "bank": 12,
  "pedalboard": "../pedalboard.json",
  "surface": "../surfaces/lead.json",
  "chain": ["L2", "L5", "L7"],
  "programs": {"live": "crunch", "reverb": "hall"},
  "snapshots": [
    {"name": "Intro", "loops": ["L5"], "params": {"live.delay": "on"}},
    {"name": "Chorus", "loops": ["L2", "L5"], "params": {"live.drive": "on", "live.delay": "on"}}
  ]
}
```

- `chain` : ordre des loops utilisées ; les loops non citées sont rangées
  après, coupées. Les montages parallèles passent par la notation de l'écran
  (`routing.py`) au lieu d'une liste.
- Paramètre absent d'un snapshot = `off`. Une valeur peut être `on`, `off`
  ou un nombre 0–127.
- Nom de patch : `<short> <snapshot>`, 16 caractères au plus (refus sinon).

### `setup.json`

Associe les banques aux rigs (et plus tard les setlists) :

```json
{"schema": "es8ctl.setup/1", "pedalboard": "pedalboard.json",
 "rigs": {"12": "rigs/crunch-lead.json", "11": "rigs/ambient.json"}}
```

## Compilation

`compile_rig(pedalboard, surface, rig, dump) -> changes` : pur, sans MIDI,
testable sur les fixtures. Chaque élément produit :

| Source | Champs écrits | Patchs |
|---|---|---|
| `short` + nom du snapshot | `name` | chacun |
| `chain` | `loop_chain` | les 8 |
| `snapshot.loops` | `loop_sw` | chacun |
| `programs` | slots MIDI : `midi_tx_ch`, `midi_pc`, `midi_pc_bank_*`, `midi_transmit` | les 8, identiques |
| `snapshot.params` | `midi_ctl1/2_cc`, `midi_ctl1/2_cc_val` des slots | chacun |
| switch `param` | un assign : source `NUMx`, cible `MIDI`, `assign_target_cc_ch/no`, `assign_mode`, min/max | les 8 |
| switch `tap` | `ctl_func[NUM_x] = BPM` | les 8 |
| switch `loop` | `manual_number<x>` | **système** |

Rangement des slots MIDI (8 par patch, chacun : canal, PC, 2 CC) : par
appareil, le premier slot porte le PC du rig et 2 CC, les suivants (même
canal, sans PC) 2 CC chacun.

Le compilateur rend aussi la liste des champs qu'il possède (`owns`) : badges
dans l'éditeur classique et détection de divergence.

### Vérifications (refus avant toute écriture)

- 8 snapshots au plus ; noms ≤ 16 caractères.
- Assigns ≤ 12, slots MIDI ≤ 8 par patch.
- Loops de la chaîne et des snapshots présentes dans le pedalboard.
- Paramètres et programmes existants ; canaux distincts entre appareils.
- Champs système : deux surfaces en usage ne peuvent pas donner deux valeurs
  au même `manual_number`.

Avertissements (sans refus) : appareil `repeated_pc: reloads` ou `unknown`,
loop câblée inutilisée, slot de snapshot vide.

### Divergence et import

- **Divergence** : après un `read`, recompiler le rig contre le dump frais.
  Changements vides = synchronisé ; sinon la banque a été modifiée sur la
  pédale. Choix : réappliquer le rig, ou reprendre les valeurs de la pédale.
- **Import** (`es8ctl rig import --bank 12`) : brouillon de rig depuis une
  banque existante. Ce qui est identique dans les 8 patchs remonte au rig
  (chaîne, PC, assigns) ; ce qui varie devient l'état des snapshots. Même
  mécanique que la reprise des valeurs en cas de divergence.

## Interface : une app à part

Deux apps, un moteur :

```
web/
  shared/   engine.js (Pyodide, Web MIDI, lecture, écriture vérifiée), styles de base
  editor/   l'éditeur classique actuel (champ par champ)
  rigs/     Pedalboard, Rig, Surface, Écriture et moniteur
```

- Toute la logique reste dans la lib Python (`compile_rig`, `_accept`,
  `write_pending`) ; rien n'est réimplémenté en JS.
- Pont web : `stage_rig(json)` → `_accept(compile_rig(...))`. Le résultat
  rejoint les modifications en attente et s'écrit par le même chemin
  (sauvegarde, relecture, renvoi).
- Liens croisés : « ouvrir ce patch dans l'éditeur classique » ; l'éditeur
  classique lit `setup.json` et marque les champs « gérés par le rig X ».
- Une seule app connectée à l'ES-8 à la fois (verrou) : deux connexions
  recevraient les mêmes réponses et deux files d'attente s'écraseraient.

## À tester sur l'appareil avant de coder la compilation

1. Au rappel d'un patch, l'état des toggles du mode manuel repart-il du patch
   (`led_numX`, état des assigns) ou garde-t-il la dernière valeur ?
2. Un assign `NUMx` → `MIDI` en `TGL` : la LED du switch suit-elle l'appui ?
3. L'ES-8 renvoie-t-il un PC identique au changement de patch (moniteur) ?
4. Encodage de `midi_pc` (0 = rien envoyé ?) et de `manual_number` (0–9).
5. Le canal d'écoute de la source d'assign `CC` est-il le canal de réception
   système ? (utile seulement pour un retour visuel piloté de l'extérieur)
