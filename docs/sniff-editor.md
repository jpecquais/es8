# Écouter l'éditeur officiel (étape 4 du plan)

But : capturer la commande que l'éditeur BOSS ES-8 envoie pour **lire**
l'appareil (non documentée : l'ES-8 ne répond ni à RQ1 ni à l'identité
MIDI), et les messages d'**édition en temps réel**.

## Principe : le Mac sert d'intermédiaire

```
Éditeur (Windows) ──rtpMIDI (réseau)──▶ Mac ──WIDI (Bluetooth)──▶ ES-8
                   ◀──────────────────     ◀──────────────────
                         es8ctl sniff : relaie et journalise tout
```

Avantages : pas de WIDI ni de pilote Bluetooth à installer sous Windows
(Windows 10 gère mal le BLE-MIDI pour les applications classiques) ; le
journal est écrit directement sur le Mac, dans le format que nos outils lisent.

## Mise en place

### Mac

1. *Configuration audio et MIDI* → menu *Fenêtre* → *Afficher le studio
   MIDI* → double-cliquer *Réseau*.
2. Activer la session (« Session 1 »), *Qui peut se connecter* : « Tout le
   monde » (le temps de la capture).
3. Le WIDI reste connecté au Mac, comme d'habitude.

### Windows 10

1. Installer **rtpMIDI** (Tobias Erichsen, gratuit).
2. Dans rtpMIDI : *Directory* doit montrer la session du Mac ; la
   sélectionner et *Connect*. (Sinon : *Participants* → ajouter l'IP du Mac,
   port 5004.)
3. Installer l'**éditeur BOSS ES-8**.
4. Dans l'éditeur : *Option* → *MIDI Device IN* et *OUT* = la session rtpMIDI.
   Ne pas cliquer *CONNECT* tout de suite.

## Capture

Sur le Mac (l'ES-8 sur l'écran de jeu) :

```sh
es8ctl sniff --editor "Réseau Session 1" --device "WIDI Jack Bluetooth"
```

Chaque message s'affiche (`→ ES-8` / `← ES-8`) et va dans
`captures/sniff_<horodatage>.jsonl`. Puis, dans l'éditeur, **une action à la
fois, en notant l'heure** :

| # | Action dans l'éditeur | Ce qu'on cherche |
|---|---|---|
| 1 | *CONNECT* | la commande de lecture et la réponse de l'ES-8 |
| 2 | Sélectionner une autre banque | lecture d'une banque |
| 3 | Modifier le nom d'un patch | édition en temps réel (adresse du nom) |
| 4 | Basculer une loop | adresse d'une loop |
| 5 | Changer le BPM | adresse d'un champ large |
| 6 | *WRITE* sur un patch de test | écriture par l'éditeur (bulk ou autre ?) |
| 7 | Modifier Tempo Hold (réglages système) | position de `tempo_hold` |

`Ctrl-C` arrête le relais et affiche le nombre de messages par sens.

## Sûreté

Le relais ne transmet à l'ES-8 que ce que l'éditeur officiel envoie. Les
écritures (*WRITE*) se font sur l'ES-8 de test.
