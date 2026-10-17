# es8ctl

Éditeur open-source pour le Boss ES-8. Voir `PLAN.md` pour la spécification
et la séquence de travail.

## État actuel

Préparation de la session hardware n°1 (étape 0 du plan) : accueillir le
premier bulk dump SysEx de l'ES-8. Le codec Roland (enveloppe + checksum)
est implémenté et testé sans matériel. Aucune écriture vers l'ES-8 n'existe
encore — l'outil est read-only.

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

   Sans `--port`, la commande est interactive. `Ctrl-C` termine la capture.
   Sortie : `captures/dump_<horodatage>.syx` + sidecar `.json` (métadonnées
   et en-têtes décodés de chaque trame).

4. Un fichier `.syx` peut être ré-analysé hors ligne :

   ```sh
   es8ctl inspect captures/dump_<horodatage>.syx
   ```

## Structure

```
src/es8ctl/
  cli.py          # typer : devices · capture · inspect
  capture.py      # écoute MIDI, enregistrement, sidecar JSON
  codec/
    roland.py     # enveloppe SysEx Roland, checksum, décodage DT1/RQ1
tests/
captures/         # dumps bruts de la session hardware (voir captures/README.md)
```
