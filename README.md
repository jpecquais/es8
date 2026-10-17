# es8ctl

Éditeur open-source pour le Boss ES-8. Voir `PLAN.md` pour la spécification
et la séquence de travail.

## État actuel

Étape 0 terminée : bulk dump capturé, déterministe, encodé/décodé bit à bit.
Étape 1 en cours : organisation du dump (bloc système + 800 patchs) et
encodage des patchs (empaquetage 8→7, flux de bits) établis ; les noms de
patch sont décodés. La carte des autres champs se construit par dumps
différentiels — voir `docs/bulk-format.md`. Aucune écriture vers l'ES-8
n'existe : l'outil est read-only.

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
   (premières trames) est perdu. Sans `--port`, la commande est interactive. `Ctrl-C` termine la capture.
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

## Structure

```
src/es8ctl/
  cli.py          # typer : devices · capture · inspect · diff
  capture.py      # écoute MIDI, enregistrement, sidecar JSON
  diff.py         # comparaison de dumps (système, patchs bit à bit)
  codec/
    roland.py     # enveloppe SysEx Roland, checksum, décodage DT1/RQ1
    es8.py        # trames de bulk ES-8, découpage, empaquetage 8→7, noms
docs/
  bulk-format.md  # notes de RE + protocole des dumps différentiels
tests/
captures/         # dumps bruts de la session hardware (voir captures/README.md)
```
