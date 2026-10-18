# es8ctl — Plan d'action

Éditeur open-source pour le Boss ES-8, pilotable par IA via CLI.
Spéc complète : voir §Références. Ce document fixe les décisions, les corrections
apportées par la recherche initiale, et la séquence de travail.

## 0. Avancement (2026-10-18)

| Étape | État | Détail |
|---|---|---|
| 0 — Session hardware n°1 | ✅ | Dump initié au panneau ; 1616 trames ; fixture n°1 |
| 1 — Noyau offline | ✅ | Format complet décodé (spec Roland v1 recalée sur v2), round-trip bit à bit, schéma JSON aligné `.bel` |
| 2 — CLI v1 | ✅ | `capture`, `diff`, `patches`, `system`, `apply` (dry-run / `--write`, backup), `verify`, `check` ; écriture vérifiée sur l'ES-8 |
| 3 — Transformations en masse | ✅ en partie | `transform set` / `swap-loops` / `variants` ; variantes vérifiées sur l'appareil (50/50), tap tempo et swap 6↔7 à écrire |
| 4 — Temps réel | 🟡 | Relais `es8ctl sniff` prêt ; capture de l'éditeur officiel à faire (`docs/sniff-editor.md`) |
| 5 — GUI / contrat agent | 🟡 | Contrat agent rédigé (`docs/agent-contract.md`) ; GUI non commencée |

Hors plan : import / export `.bel` (`es8ctl import-bel` / `export-bel`).
Détails du format et journal des essais : `docs/bulk-format.md`.

## 1. Décisions actées

- **Langage : Python** (≥ 3.11).
- **Transport : MIDI DIN via interface USB-MIDI.** *(Corrigé le 2026-10-17 :
  l'ES-8 n'a pas de port USB ; l'hypothèse initiale « USB d'abord » était
  fausse.)* Interface validée : CME WIDI Jack (Bluetooth MIDI), lecture et
  écriture. Le MIDISPORT Uno perdait des octets et n'émettait pas.
- **Offline avant temps réel.** Le palier offline (dump → éditer → restore) ne
  dépend d'aucun reverse-engineering. La carte d'adresses temps réel est un
  travail parallèle (phase 0), jamais un prérequis.
- **JSON pivot unique**, schéma versionné, dry-run par défaut, read-only par défaut.

## 2. Corrections apportées à la spec initiale

| Hypothèse initiale | Correction (recherche 2026-10-17) |
|---|---|
| Bulk dump demandé par le CLI (RQ1 hôte) | Confirmé : le dump est **initié au panneau** ; l'ES-8 ne répond à aucune requête RQ1 connue. `capture` = mode écoute. L'éditeur officiel sait pourtant lire l'appareil : commande à capturer (étape 4). |
| Transport = DIN vers interface | Confirmé : l'ES-8 n'a pas d'USB, le DIN via interface est le seul transport. |
| `.bel` partiellement cartographié | Confirmé : `es8-bulk-editor` (qckpckt) ne touche jamais le MIDI, ne traite que des `.bel` (mapping surtout sur les assigns ; projet quasi inactif). Utilisable comme **oracle sémantique**, pas comme base de code. |
| Carte d'adresses temps réel | Aucune carte publiée n'existe. Le RE (phase 0) est réellement nécessaire. |
| Format du bulk dump inconnu | Roland publie la spec du bulk dump (firmware v1) : positions et bornes de chaque paramètre. Le v2 insère 27 bits ; tout est recalé et validé. |

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
