# es8ctl

Éditeur open-source pour le Boss ES-8. Voir `PLAN.md` pour la spécification
et la séquence de travail.

## État actuel

Étapes 1 et 2 terminées : dump décodé en entier (patchs et système),
écriture vérifiée sur l'appareil. Étape 3 : transformations en masse
(`es8ctl transform`), les trois cas d'usage cibles passent en une commande.
Import / export `.bel` (format de l'éditeur officiel). **En cours :**
écrire les transformations en masse sur l'appareil — voir « Prochaine
session matériel » dans `docs/bulk-format.md`.

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
  cli.py          # typer : devices · capture · inspect · diff · patches · system · transform · apply · verify · check · export-bel · import-bel
  capture.py      # écoute MIDI, enregistrement, sidecar JSON
  diff.py         # comparaison de dumps (système, patchs bit à bit)
  layout.py       # champs empaquetés au bit ↔ JSON (mécanique commune)
  patch.py        # carte complète des champs de patch (v2)
  system.py       # carte du bloc système (v2)
  names.py        # noms symboliques (NUM_8, BPM, L6…)
  routing.py      # chaîne de loops ↔ notation écran (V8746(3//5)21)
  transform.py    # transformations en masse → changements JSON
  bel.py          # import / export .bel (éditeur officiel)
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

## Transformations en masse

`es8ctl transform` produit un JSON de changements, à passer à `es8ctl apply`
(simulation, sauvegarde et vérification restent au même endroit). Index et
valeurs symboliques acceptés (`NUM_8`, `BPM`, `L6`…). Chaîne de loops en
notation écran : `"loop_chain": "V8746(3//5)21"` (`//` = parallèle).

```sh
# Footswitch 8 en tap tempo sur tous les patchs
es8ctl transform set "ctl_func[NUM_8]=BPM" -b captures/<dump>.syx -o tap.json

# Échanger les loops 6 et 7 partout (interrupteurs, carry-over, assigns, chaîne)
es8ctl transform swap-loops 6 7 -b captures/<dump>.syx -o swap.json

# 50 variantes du patch 0-8 aux routings différents, dans 10-1 … 16-2
es8ctl transform variants 0-8 --into 10-1 -n 50 -b captures/<dump>.syx -o var.json

es8ctl apply var.json --base captures/<dump>.syx            # simulation
```

`--patches 0-1..9-8` restreint `set` et `swap-loops` ; `variants` refuse
d'écraser un patch non vierge sans `--overwrite`.

## Écrire vers l'ES-8

**Précondition : l'ES-8 doit être sur l'écran de jeu.** Après un dump
déclenché au panneau, il reste sur l'écran Bulk Dump, où il ignore sans
erreur tout ce qu'il reçoit : quitter cet écran (EXIT) avant d'écrire.

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
   interrompue (partielle). Rythme : `--interval` entre les deux messages
   d'une page (défaut 60 ms), `--page-gap` entre deux pages (défaut 0,5 s).

4. Re-dumper et vérifier (code 0 si conforme) :

   ```sh
   es8ctl capture
   es8ctl verify captures/expected_<horodatage>.syx captures/<nouveau dump>.syx
   es8ctl check changes.json captures/<nouveau dump>.syx   # patch par patch
   ```

## Format `.bel` (éditeur officiel)

```sh
es8ctl export-bel captures/<dump>.syx -o mon_es8.bel
es8ctl import-bel fichier.bel --base captures/<dump>.syx -o changes.json
es8ctl apply changes.json --base captures/<dump>.syx
```

Clés et ordre identiques à ceux de l'éditeur. Limites (signalées) : 10 clés
système non localisées (`MANUAL_NUMBER1-8`, `TEMPO_HOLD`, `LINK`) ; le
patch 99-8, dont le dernier message n'est jamais reçu, est complété par la
seconde moitié du patch d'usine.
