# es8ctl — Plan d'action

Éditeur open-source pour le Boss ES-8, pilotable par IA via CLI.
Spéc complète : voir §Références. Ce document fixe les décisions, les corrections
apportées par la recherche initiale, et la séquence de travail.

## 1. Décisions actées

- **Langage : Python** (≥ 3.11).
- **Transport : MIDI DIN via interface USB-MIDI.** *(Corrigé le 2026-10-17 :
  l'ES-8 n'a pas de port USB ; l'hypothèse initiale « USB d'abord » était
  fausse.)* Interface actuelle : M-Audio MIDISPORT Uno — réception OK mais
  pertes d'octets occasionnelles, émission non fonctionnelle à ce jour.
- **Offline avant temps réel.** Le palier offline (dump → éditer → restore) ne
  dépend d'aucun reverse-engineering. La carte d'adresses temps réel est un
  travail parallèle (phase 0), jamais un prérequis.
- **JSON pivot unique**, schéma versionné, dry-run par défaut, read-only par défaut.

## 2. Corrections apportées à la spec initiale

| Hypothèse initiale | Correction (recherche 2026-10-17) |
|---|---|
| Bulk dump demandé par le CLI (RQ1 hôte) | À vérifier dès la session hardware n°1 : la procédure officielle suggère que le dump est **initié au panneau de l'ES-8**. Si confirmé, `dump` = mode écoute et le diagramme de séquence change. |
| Transport = DIN vers interface | Confirmé : l'ES-8 n'a pas d'USB, le DIN via interface est le seul transport. |
| `.bel` partiellement cartographié | Confirmé : `es8-bulk-editor` (qckpckt) ne touche jamais le MIDI, ne traite que des `.bel` (mapping surtout sur les assigns ; projet quasi inactif). Utilisable comme **oracle sémantique**, pas comme base de code. |
| Carte d'adresses temps réel | Aucune carte publiée n'existe. Le RE (phase 0) est réellement nécessaire. |

## 3. Stack Python (proposition, ajustable)

| Besoin | Choix proposé | Motif |
|---|---|---|
| CLI | `typer` | JSON-first, typage, ergonomie agent |
| MIDI | `mido` + backend `python-rtmidi` | CoreMIDI/ALSA/WinMM couverts par la même API |
| Schéma / validation | `pydantic` v2 | validation stricte à l'entrée, versionnage du schéma |
| Tests | `pytest` + fixtures = dumps capturés | noyau testable sans matériel |
| Packaging | `uv` / `pyproject.toml` | installation simple, binaire `es8ctl` en point d'entrée |

## 4. Séquence de travail

### Étape 0 — Session hardware n°1 (30 min, zéro code)

Brancher l'ES-8 en USB sur le Mac, capturer un bulk dump brut avec un simple
utilisateur d'écoute SysEx. Objectifs :

1. Trancher : dump initié au panneau ou via requête hôte (change la forme du CLI).
2. Lire device ID + model ID réels (dans la première trame).
3. Mesurer taille et durée réelles du dump complet → décide si la reprise sur
   interruption est une exigence P1 ou une option.
4. Conserver le dump brut : il devient la **fixture de test n°1** de tout le noyau.

Risque : aucun (lecture seule).

### Étape 1 — Noyau offline sans matériel

- Codec SysEx Roland (DT1/RQ1, checksum : somme addr+data, complément à 2 sur 7 bits).
- Décodeur générique : séparateur device ID / model ID / commande / adresse / données.
- Schéma JSON v1 des patches, aligné sur la sémantique `.bel` (oracle :
  `test_1.bel` du repo es8-bulk-editor + un `.bel` de notre ES-8).
- Validation stricte à l'entrée : tout patch hors schéma rejeté avant tout envoi.
- Tout testé sur la fixture de l'étape 0, sans ES-8 branché.

Critère de sortie : dump brut → document JSON versionné → re-encodage bit à bit
identique au dump d'origine (round-trip sur fixture).

### Étape 2 — CLI v1 (offline)

Commandes : `devices`, `dump`, `diff`, `apply` (dry-run par défaut, `--write`
opt-in), `verify` (re-dump et comparaison), `get`/`set`.

Conventions non négociables : sortie JSON machine-first (`--pretty` pour
l'humain), codes de sortie déterministes, dry-run par défaut, backup horodaté
automatique avant toute écriture.

Critère de sortie : round-trip complet vérifié sur le vrai matériel,
vérification après écriture, sans régression de données.

### Étape 3 — Transformations en masse (P2)

Moteur de transformations du noyau : template + masques, swap de loops,
assigns globaux. Les trois cas d'usage cibles de la spec doivent passer en une
commande :

- « footswitch 8 en tap tempo sur tous les patches »
- « échange les loops 6 et 7 partout »
- « génère 50 variantes de ce patch avec des routings différents »

### Étape 4 — Temps réel (P3), en parallèle dès que possible

1. Corpus de captures : sniffer l'éditeur officiel (Windows LTSC) ↔ ES-8,
   un paramètre à la fois, journal de session associé à chaque capture.
2. Décodage automatique des trames (le codec existe déjà, étape 1).
3. Inférence de la carte d'adresses : rapprochement journal ↔ trames.
4. Réplication : rejouer une trame capturée depuis le Mac et confirmer l'effet.

Sortie : carte d'adresses en fichier de données versionné, niveau de confiance
par paramètre. Puis `watch` / édition live.

### Étape 5 — GUI (P4), puis contrat agent (P5)

La GUI s'appuie sur la même lib que le CLI, sans logique dupliquée. Le contrat
agent est documenté : le LLM n'accède qu'au CLI, jamais au MIDI.

## 5. Sûreté (règles permanentes)

- Read-only par défaut ; écriture uniquement via sous-commande explicite + `--write`.
- Backup horodaté automatique avant toute écriture, jamais écrasé.
- Checksums vérifiés à l'envoi et à la réception ; trame invalide = erreur explicite.
- Verify-after-write : re-dump et comparaison après chaque restore.
- Test du comportement sur restore partiel interrompu : très tôt, sur une
  banque sacrifiable.
- Le schéma trace la version firmware (écart v1/v2).

## 6. Questions ouvertes à fermer en cours de route

- Panneau vs requête hôte pour le dump (étape 0).
- Dump binaire brut vs `.bel` : structure identique ou non (étape 1).
- Débit réel USB vs DIN pour un dump complet (étape 0).
- Comportement de l'ES-8 sur réception partielle d'un restore (dès l'étape 2).

## 7. Références

- Procédure bulk dump officielle : https://support.roland.com/hc/en-us/articles/208191746
- Restauration : https://support.roland.com/hc/en-us/articles/212319526
- Manuel ES-8 Editor : https://static.roland.com/assets/media/pdf/ES-8_Editor_eng02_W.pdf
- Format d'enveloppe SysEx Roland : https://www.2writers.com/eddie/TutSysEx.htm
- es8-bulk-editor (oracle `.bel`) : https://github.com/qckpckt/es8-bulk-editor
