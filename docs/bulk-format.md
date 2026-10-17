# Format du bulk dump ES-8 — notes de reverse-engineering

État au 2026-10-17. Fixtures (capture DIN via M-Audio MIDISPORT Uno) :

- `es8_bulk_session1.syx` : compteurs 16–1614, sans bloc système.
- `es8_bulk_session2_name_A.syx` : compteurs 0–1614, patch 1-1 renommé
  `AAAAAAAAAAAAAAAA`, tout le reste identique.

## Établi

### Trames et organisation

- Trame : `F0 41 00 00 00 00 14 12 <ctr_hi> <ctr_lo> <143 octets> <checksum> F7`.
- Compteurs 0–15 : **bloc système** (16 trames, 2288 octets MIDI).
- Compteurs 16+2k et 17+2k : **patch k** (1-1 = k 0, banque-numéro = k÷8+1 – k mod 8+1).
  Confirmé : renommer 1-1 ne modifie que la trame 16.
- Le dump s'arrête au compteur 1614 : le patch 100-8 n'a que sa première trame.

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

`loop_position` : 0–9 apparaissent une fois chacun, 10–15 deux fois et
s'intercalent entre les loops (TOC-FAT : `…6, 10, 5, 11, 3, 12…`) —
probablement des marqueurs de branches série/parallèle, à confirmer.

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

## Questions ouvertes

1. **Dernière trame manquante.** La spec liste le message `0C 4F` (patch
   100-8, seconde moitié) : le dump complet fait 1616 trames. Les captures
   s'arrêtent toutes à `0C 4E`. Trame perdue par l'interface DIN ou par la
   capture ? À tester en USB. En attendant, `capture` s'arrête sur `0C 4E`.
2. Position de `manual_number1-8`, `tempo_hold`, `link` dans la page système 1.
3. Confirmer par dump les champs `inferred` (`mixer_*`, `midi_clock_out`,
   `midi_transmit`, extension système v2) et le sens des marqueurs 10–15 de
   `loop_position`.

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
sur 1-1, MIDI clock out d'un patch, un réglage système (contraste LCD), sens
des marqueurs 10–15 de `loop_position`, position de `tempo_hold` (basculer
le réglage, comparer le bloc système).
