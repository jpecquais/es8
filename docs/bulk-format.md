# Format du bulk dump ES-8 — notes de reverse-engineering

État au 2026-10-17. Fixtures (capture DIN via M-Audio MIDISPORT Uno) :

- `es8_bulk_session1.syx` : compteurs 16–1614, sans bloc système.
- `es8_bulk_session2_name_A.syx` : compteurs 0–1614, patch 0-1 (le premier) renommé
  `AAAAAAAAAAAAAAAA`, tout le reste identique.

## Établi

### Trames et organisation

- Trame : `F0 41 00 00 00 00 14 12 <ctr_hi> <ctr_lo> <143 octets> <checksum> F7`.
- Compteurs 0–15 : **bloc système** (16 trames, 2288 octets MIDI).
- Compteurs 16+2k et 17+2k : **patch k** (0-1 = k 0, banque-numéro = k÷8 – k mod 8+1 ; banques
  numérotées à partir de 0, comme sur l'écran de l'ES-8 et dans la spec).
  Confirmé : renommer 0-1 ne modifie que la trame 16.
- Le dump s'arrête au compteur 1614 : le patch 99-8 n'a que sa première trame.

### Encodage d'une page (2 × 143 octets MIDI → 250 octets de données)

- Une page (système ou patch) = 250 octets, transmis en **deux messages de
  125 octets encodés séparément** (`unpack_page` / `pack_page`).
- Chaque message : groupes de 8 octets MIDI, 1 octet porteur + 7 octets de
  données. Bit 6 du porteur = bit 7 du 1er octet de données, bit 5 = bit 7
  du 2e, etc. 17 groupes + un groupe final porteur + 6 = 143 → 125 octets.
- Les 250 octets forment un **flux de bits MSB d'abord** : les champs y sont
  empaquetés sans alignement sur l'octet.
- Round-trip `pack_page(unpack_page(r)) == r` vérifié sur toutes les pages.

Piège rencontré : dépaqueter les 286 octets d'un seul tenant donne aussi
250 octets sans erreur, identiques jusqu'à l'octet 124, mais décalés
ensuite. Symptômes : tables de program change incohérentes à partir de
l'entrée 100, valeurs disparates dans les assigns du patch d'usine. Les
tests vérifient désormais ces deux points.

### Carte des champs (patch, bits dépaquetés)

**Référence officielle :** Roland, *ES-8 Bulk Dump Messages* v1.00 (2015),
<https://static.roland.com/assets/media/pdf/ES-8_Bulk_Dump_Messages_e01_W.pdf>.
Elle donne, pour chaque paramètre système et patch, octet, bit (compté depuis
le MSB), largeur et bornes. Elle confirme tout ce qui précède : pages de
250 octets, encodage 7 bits par groupes de 8, champs empaquetés au bit.

La spec décrit le **firmware v1**. Le firmware v2 (celui de l'ES-8 étudié et
du `.bel` de l'éditeur) diffère ainsi :

- `loop_position` : 22 valeurs au lieu de 16 (+24 bits) ;
- `mixer_mode`, `mixer_gain1`, `mixer_gain2` insérés après (+3 bits, 1 bit
  chacun supposé) → tout ce qui suit est décalé de **+27 bits** ;
- `midi_clock_out` (1) et `midi_transmit` (8 × 1) ajoutés en fin de page :
  1998 bits utilisés, 2 bits de bourrage à zéro.

Les bornes v1 tiennent sur toutes les valeurs observées.

Validation sur les 2 × 799 patchs des fixtures : ancres expérimentales
(`loop_sw` bit 0, `master_bpm` bit 186 = 159 + 27, `name` bit 195 = 168 + 27),
patch d'usine identique aux défauts du `.bel` (EXP1 128, EXP2 129, BPM 120,
et sur les 12 assigns : CC 80, temps 30, vitesse 7, forme 2), aucune valeur
hors bornes, round-trip bit à bit.

Carte en code : `src/es8ctl/patch.py` (`PATCH_FIELDS`, avec un niveau de
confiance par champ : `confirmed` / `spec` / `inferred`).

Défaut usine : `BOSS ES-8       `, 120 BPM.

`loop_position` = **ordre de la chaîne** (confirmé sur l'écran de l'ES-8 :
0-3 `87654321V`, 0-8 `V87465321`, 6-2 `V8746(3//5)21`) :

- 0 = V, 1–8 = L1–L8 ;
- 10 / 11 / 12 = début / séparateur / fin d'un parallèle ; 13 / 14 / 15 =
  second jeu de marqueurs (affichage non observé) ; deux exemplaires de
  chaque marqueur ;
- 9 termine la chaîne ; la réserve de marqueurs inutilisés suit, dans un
  ordre qui varie d'un patch à l'autre (conservé lors des modifications) ;
- l'écran présente les deux branches d'un parallèle dans l'ordre inverse
  de la liste (`10 5 11 3 12` → `(3//5)`) ; une branche peut être vide.

Code : `src/es8ctl/routing.py` (notation écran ↔ liste, `loop_chain` dans
`patches` et `apply`).

### Bloc système (8 pages)

- Page 1 : bits 0–84 conformes à la spec v1 (`current_num` … `memory_manual`).
  Le v2 ajoute ensuite les fonctions CTL/EXP du mode manuel (`ctl_sw`,
  `ctl_func`, `ctl_min/max/mod`, `exp_sw/func/min/max`) jusqu'au bit 270,
  aux largeurs des champs de patch équivalents : lecture conforme aux
  défauts du `.bel` (`ctl_sw` [0, 1, 0…], `ctl_func` [1, 2, 3, 4, 7…]).
- Pages 2–8 : `pc_map_bank0_pc` … `pc_map_bank6_pc`, 128 × 10 bits (patch
  rappelé par chaque program change). Identité sur la fixture.
- Non localisés : `manual_number1-8`, `tempo_hold`, `link` (listés par le
  `.bel`). Bits 271+ de la page 1 à zéro sur la fixture ; `encode_system`
  les conserve tels quels.

Carte en code : `src/es8ctl/system.py`. Mécanique commune : `src/es8ctl/layout.py`.

### Transmission vers l'ES-8 (pour l'écriture, étape 2)

D'après la spec : les deux messages d'une page doivent être envoyés à la
suite, dans l'ordre ; un message seul est invalide ; **au moins 50 ms entre
deux messages**. Des données incohérentes peuvent faire dysfonctionner l'ES-8.

### Premier essai d'écriture (2026-10-18)

Via un CME WIDI Jack (Bluetooth MIDI) branché sur l'ES-8 : une seule page
(patch 49-1, nom + BPM) envoyée par `es8ctl apply --write` est acceptée et
enregistrée. L'ES-8 accepte donc une page isolée, sans dump complet. Via le
MIDISPORT Uno, rien n'atteignait l'ES-8, pas même un Program Change.

### Écriture de nombreuses pages (2026-10-18)

**L'ES-8 ignore tout bulk dump reçu tant qu'il est sur l'écran Utility >
Bulk Dump**, où il reste après un dump déclenché au panneau. Aucune erreur
n'est signalée. Tous les échecs d'écriture via le WIDI s'expliquent ainsi :

| Envoi | État de l'ES-8 | Résultat (vérifié par dump) |
|---|---|---|
| 1 page (49-1) | écran de jeu | ✅ |
| 50 pages, 60 ms continus | juste après un dump | 5 / 50 |
| 45 pages, 300 ms continus | juste après un dump | 0 / 45 |
| 1 page (10-3) | écran de jeu (l'utilisateur venait de naviguer) | ✅ |
| 3 lots, pause 1,0 / 0,5 / 0,2 s entre pages | juste après un dump | 0 / 44 (×2, liaison vérifiée avant/après) |
| 44 pages, précédées de 2 Program Change | juste après un dump | 0 / 44 (les PC ne quittent pas l'écran) |
| 5 pages, une par `apply` | juste après un dump | 0 / 5 |
| **44 pages, pause 0,5 s** | **écran de jeu (EXIT à la main)** | **✅** |

Rythme retenu : 60 ms entre les deux moitiés d'une page, 0,5 s entre pages
(défauts de `apply`). Un rythme plus rapide reste à tester sur l'écran de jeu.

Le WIDI répond lui-même à la requête d'identité universelle
(`F0 7E 7F 06 02 00 20 63 …`, CME) : c'est un test de la liaison Bluetooth
(Mac ↔ WIDI), pas de la prise DIN ni de l'ES-8. L'ES-8 ne répond ni à RQ1 ni
à l'identité ; l'éditeur officiel sait pourtant lire l'appareil par MIDI
(manuel : « patch parameters … are loaded automatically ») — la commande
est à capturer en écoutant l'éditeur.

### Validation par un `.bel` de l'éditeur officiel

Le `test_1.bel` de l'oracle (autre ES-8, exporté par l'éditeur BOSS)
s'importe sans aucune valeur hors bornes ; 649 de ses 800 patchs sont
identiques, champ par champ, à notre décodage des patchs d'usine. Nos
champs ont les mêmes noms et le même ordre que les clés du `.bel` (seule
exception : `ID_PATCH_LOOP_SW_LOOP` ↔ `loop_sw`). Les 10 clés système non
localisées suivent `EXP_MAX` dans le `.bel` : elles sont très probablement
aux bits 271+ de la page système 1 (à zéro sur nos dumps).

### Fiabilité de la liaison DIN (MIDISPORT Uno)

Le dump 4 (`dump_20261017_195509`) contient une trame de 152 octets au lieu
de 155 (compteur 1393, 3 octets perdus) : le checksum l'a détectée. Avec les
pauses de plusieurs minutes en cours de dump, c'est un argument pour l'USB.
À l'écriture, une trame corrompue en route peut être rejetée par l'ES-8 —
ou, avec une faible probabilité, passer le checksum : d'où la vérification
systématique par re-dump.

## Prochaine session matériel

Toujours : lancer la capture avant le dump, et **quitter l'écran Bulk Dump
avant d'écrire**.

1. Basculer `Tempo Hold` dans les réglages système, dumper, `es8ctl diff`
   → position de `tempo_hold` (puis `LINK`, `MANUAL_NUMBER`).
2. Écrire les transformations en masse (tap tempo partout, échange 6 ↔ 7)
   et vérifier avec `es8ctl check`.
3. Tester un rythme plus rapide (`--page-gap 0.2`) sur l'écran de jeu.
4. Écouter l'éditeur officiel (Windows) pour trouver la commande de lecture
   et l'édition en temps réel.

## Questions ouvertes

1. ~~Dernière trame manquante~~ : résolu, un dump complet fait 1616 trames
   (jusqu'à `0C 4F`) ; les premières captures s'arrêtaient trop tôt.
2. Position de `manual_number1-8`, `tempo_hold`, `link` dans la page système 1.
3. Comportement de l'ES-8 à la réception d'une seule page (écriture
   partielle) : à vérifier au premier essai d'écriture.
4. Confirmer par dump les champs `inferred` (`mixer_*`, `midi_clock_out`,
   `midi_transmit`, extension système v2) et l'affichage des parallèles du
   second jeu (13–15).

## Protocole — dumps différentiels

**Lancer `es8ctl capture` avant de déclencher le dump au panneau**, sinon
les premières trames (le bloc système) sont perdues. L'envoi peut faire
une **pause de plusieurs minutes** en cours de route (dump 2 : arrêt au
compteur 844 pendant ~4 min, puis reprise jusqu'au bout) : ne pas arrêter la
capture avant le compteur 1614 (1615 trames).

```sh
es8ctl capture -o captures/          # référence
# modifier UN paramètre au panneau, puis :
es8ctl capture -o captures/
es8ctl diff captures/<ref>.syx captures/<new>.syx
```

`diff` rapporte, par patch, les plages de bits modifiées (positions dans le
flux dépaqueté) avec leurs valeurs avant/après. Consigner chaque expérience
(paramètre, patch, ancienne → nouvelle valeur) avec le nom du fichier.

Avec la spec officielle, les dumps différentiels ne servent plus qu'à
confirmer les champs marqués `inferred` et les écarts v2 : réglage du mixer
sur 0-1, MIDI clock out d'un patch, un réglage système (contraste LCD), sens
des marqueurs 10–15 de `loop_position`, position de `tempo_hold` (basculer
le réglage, comparer le bloc système).
