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

### Encodage d'un patch (286 octets MIDI → 250 octets de données)

- Groupes de 8 octets MIDI : 1 octet porteur + 7 octets de données. Bit 6 du
  porteur = bit 7 du 1er octet de données, bit 5 = bit 7 du 2e, etc.
- Dernier groupe partiel : porteur + 5 données. 35 × 7 + 5 = 250 octets.
- Empaquetage local à chaque patch (pas de flux continu entre patchs).
- Les 250 octets forment un **flux de bits MSB d'abord** : les champs y sont
  empaquetés sans alignement sur l'octet (`.bel` : 418 valeurs pour 2000 bits).
- Round-trip `pack_8to7(unpack_7to8(r)) == r` vérifié sur les 2 × 799 patchs.

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
  1998 bits utilisés, 2 bits de bourrage à zéro ;
- plages élargies sur des assigns actifs : `assign_source` jusqu'à 25,
  `assign_wave_pedal_rate` à 0, `assign_wave_pedal_form` à 3.

Validation sur les 2 × 799 patchs des fixtures : ancres expérimentales
(`loop_sw` bit 0, `master_bpm` bit 186 = 159 + 27, `name` bit 195 = 168 + 27),
patch d'usine identique aux défauts du `.bel` (EXP1 128, EXP2 129, BPM 120,
CC 80, temps 30…), aucune valeur hors bornes, round-trip bit à bit.

Carte en code : `src/es8ctl/patch.py` (`PATCH_FIELDS`, avec un niveau de
confiance par champ : `confirmed` / `spec` / `inferred`).

Défaut usine : `BOSS ES-8       `, 120 BPM.

`loop_position` : 0–9 apparaissent une fois chacun, 10–15 deux fois et
s'intercalent entre les loops (TOC-FAT : `…6, 10, 5, 11, 3, 12…`) —
probablement des marqueurs de branches série/parallèle, à confirmer.

### Transmission vers l'ES-8 (pour l'écriture, étape 2)

D'après la spec : les deux messages d'une page doivent être envoyés à la
suite, dans l'ordre ; un message seul est invalide ; **au moins 50 ms entre
deux messages**. Des données incohérentes peuvent faire dysfonctionner l'ES-8.

## Questions ouvertes

1. **Dernière trame manquante.** La spec liste le message `0C 4F` (patch
   100-8, seconde moitié) : le dump complet fait 1616 trames. Les captures
   s'arrêtent toutes à `0C 4E`. Trame perdue par l'interface DIN ou par la
   capture ? À tester en USB. En attendant, `capture` s'arrête sur `0C 4E`.
2. Bloc système : 8 pages dans la spec (page 1 = réglages, pages 2–8 =
   tables de program change), à décoder et à confronter au v2.
3. Confirmer par dump les champs `inferred` (`mixer_*`, `midi_clock_out`,
   `midi_transmit`) et le sens des marqueurs 10–15 de `loop_position`.

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
des marqueurs 10–15 de `loop_position`.
