# es8ctl

Éditeur open-source pour le Boss ES-8. Voir `PLAN.md` pour la spécification
et la séquence de travail.

## État actuel

Étape 1 terminée : le bulk dump est capturé, encodé/décodé bit à bit, et
**les patchs comme le bloc système sont décodés** (`es8ctl patches`,
`es8ctl system`), grâce à la spec officielle Roland (firmware v1) recalée
sur le firmware v2 — voir `docs/bulk-format.md`. Étape 2 en cours :
`es8ctl apply` (simulation par défaut, `--write` pour envoyer) et
`es8ctl verify` ; **première écriture réelle réussie** (une page, via
Bluetooth MIDI). Les patchs sont numérotés comme sur l'ES-8 : 0-1 … 99-8.

## Installation

```sh
uv sync
```

## Session hardware n°1

1. Brancher l'ES-8 en USB.
2. Lister les interfaces :

   ```sh
   es8ctl devices
   ```

3. Enregistrer le bulk dump (déclenché au panneau de l'ES-8 selon la
   procédure officielle) :

   ```sh
   es8ctl capture
   ```

   Lancer la capture **avant** de déclencher le dump, sinon le bloc système
   (premières trames) est perdu. La progression s'affiche ; la capture
   s'arrête seule à la dernière trame (compteur 1614), même si l'ES-8 marque
   une pause de plusieurs minutes en cours de route (`--no-auto-stop` pour
   écouter jusqu'au `Ctrl-C`). Sans `--port`, la commande est interactive. `Ctrl-C` termine la capture.
   Sortie : `captures/dump_<horodatage>.syx` + sidecar `.json` (métadonnées
   et en-têtes décodés de chaque trame).

4. Un fichier `.syx` peut être ré-analysé hors ligne :

   ```sh
   es8ctl inspect captures/dump_<horodatage>.syx
   ```

5. Deux dumps se comparent patch par patch, au niveau des bits dépaquetés
   (code de sortie 1 s'ils diffèrent) :

   ```sh
   es8ctl diff captures/<a>.syx captures/<b>.syx
   ```

6. Les patchs se décodent en JSON, avec les clés et la forme du `.bel` de
   l'éditeur officiel (`loop_sw`, `master_bpm`, `assign_target`…) :

   ```sh
   es8ctl patches captures/<dump>.syx            # les 799 patchs complets
   es8ctl patches captures/<dump>.syx -p 0-1 -p 2-3
   es8ctl system captures/<dump>.syx             # réglages + tables de PC
   ```

## Structure

```
src/es8ctl/
  cli.py          # typer : devices · capture · inspect · diff · patches · system · apply · verify
  capture.py      # écoute MIDI, enregistrement, sidecar JSON
  diff.py         # comparaison de dumps (système, patchs bit à bit)
  layout.py       # champs empaquetés au bit ↔ JSON (mécanique commune)
  patch.py        # carte complète des champs de patch (v2)
  system.py       # carte du bloc système (v2)
  apply.py        # changements JSON → pages → trames (validation, sans MIDI)
  transfer.py     # envoi MIDI vers l'ES-8 (seul module émetteur)
  codec/
    roland.py     # enveloppe SysEx Roland, checksum, décodage DT1/RQ1
    es8.py        # trames de bulk ES-8, découpage, pages (2 messages 8→7)
docs/
  bulk-format.md  # notes de RE + protocole des dumps différentiels
tests/
captures/         # dumps bruts de la session hardware (voir captures/README.md)
```

## Écrire vers l'ES-8

Règles : simulation par défaut ; `--write` explicite ; sauvegarde horodatée
du dump de base avant tout envoi (`backups/`, jamais écrasée) ; seules les
pages modifiées sont envoyées, 60 ms entre messages (spec : ≥ 50 ms) ;
vérification par re-dump.

1. Dump **frais** de l'ES-8 (il doit refléter l'état actuel) :

   ```sh
   es8ctl capture
   ```

2. Décrire les changements (même forme que `es8ctl patches` / `system`) :

   ```json
   {"patches": {"49-1": {"name": "ES8CTL TEST     ", "master_bpm": 99}}}
   ```

3. Simuler, puis écrire :

   ```sh
   es8ctl apply changes.json --base captures/<dump>.syx
   es8ctl apply changes.json --base captures/<dump>.syx --write --port "WIDI Jack Bluetooth"
   ```

   Codes de sortie : 0 succès, 2 changements ou base invalides, 3 écriture
   interrompue (partielle).

4. Re-dumper et vérifier (code 0 si conforme) :

   ```sh
   es8ctl capture
   es8ctl verify captures/expected_<horodatage>.syx captures/<nouveau dump>.syx
   ```
