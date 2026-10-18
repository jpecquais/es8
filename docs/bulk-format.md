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
(Mac ↔ WIDI), pas de la prise DIN ni de l'ES-8. Les premiers essais RQ1
semblaient sans réponse : ils avaient été faits sur l'écran Bulk Dump.

### Transformations en masse sur l'appareil (2026-10-18)

| Opération | Pages | 1er passage | Après renvoi |
|---|---|---|---|
| 50 variantes de 0-8 (10-1 … 16-2) | 50 | 6 + 44 (écran de jeu) | 50 / 50 |
| Tap tempo (`ctl_func[NUM_8]=BPM`) partout | 800 | 787 | 800 / 800 (renvoi manuel, puis `--confirm`) |
| Échange des loops 6 ↔ 7 partout | 800 | 785 | 800 / 800 (`--confirm`, 2 tours) |

Chaque résultat vérifié par une relecture complète (`es8ctl read`) identique
au dump attendu. Perte typique via WIDI : 1,6–1,9 % des pages au premier
passage, à 0,5 s entre pages.

### Protocole de l'éditeur officiel (lu dans son code, vérifié sur l'appareil)

L'éditeur macOS (ES-8 Editor 1.02) est une application web : sa logique
MIDI (`es_midi.js`) et sa base de paramètres (`es_parameter.js`, `prmdb`)
sont lisibles.

- **Lecture** : `F0 41 dev 00 00 00 14 11 <ID MSB> <ID LSB> <n MSB> <n LSB> <somme> F7`
  demande les messages de bulk ID … ID + n ; l'ES-8 répond au format exact
  du bulk dump. Bloc système : toute requête le rend depuis 0, borne de fin
  exclue → le lire avec 0..16. Lecture complète vérifiée : 1616 trames en
  2 min 18 via WIDI, identiques au dump panneau. `es8ctl read`.
- **Commandes DT1 `7F xx`** (données sur 2 octets) : `7F50` mode éditeur
  (0001 / 0000), `7F01` changer de patch, `7F03` mode d'affichage, `7F21`
  initialiser, `7F22` copier, `7F23` échanger (source via `7F60`), `7F24`
  renommer (caractères via `7F70`…`7F7F`).
- **Identité** : réponse `F0 7E 00 06 02 41 14 03 00 00 00 4D 00 00 F7`
  (famille 14 03). Le WIDI répond lui-même à cette requête et masque celle de
  l'ES-8 : c'est ce qui fait échouer l'éditeur via WIDI. En « MIDI Out
  Mode : THRU », l'ES-8 renvoie aussi en écho les messages Roland reçus.

**Carte des champs** : la base `prmdb` de l'éditeur (125 paramètres)
concorde avec notre carte pour la position, la largeur, le nombre et les
bornes de chaque champ, à une borne près (`assign_target` : 0–45). Elle
localise les 10 derniers champs système : `manual_number1-8` (bits 271–302,
4 bits), `tempo_hold` (303), `link` (304–305, OFF/ON/AUTO).

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

Écrire : l'ES-8 sur l'écran de jeu (EXIT après un dump au panneau). Lire :
`es8ctl read`, aucun geste requis.

1. ~~Transformations en masse~~ : faites et vérifiées.
2. Tester un rythme d'écriture plus rapide (`--page-gap 0.2`) avec `--confirm`.
3. ~~Commandes directes~~ : `es8ctl patch` (sélection, renommage, copie,
   échange, initialisation), toutes vérifiées sur l'appareil. Un patch
   initialisé = le patch d'usine avec un nom de 16 espaces.

## Questions ouvertes

1. ~~Dernière trame manquante~~ : résolu, un dump complet fait 1616 trames
   (jusqu'à `0C 4F`) ; les premières captures s'arrêtaient trop tôt.
2. ~~Position de `manual_number1-8`, `tempo_hold`, `link`~~ : résolu (base de l'éditeur).
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
