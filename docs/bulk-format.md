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

| Champ | Bit | Largeur | Encodage | Confirmé par |
|---|---|---|---|---|
| `LOOP_SW` (L1…L8, LV) | 0 | 9 × 1 | 1 = ON | L1 = bit 0 (dump 2), LV = bit 8 (dump 3) |
| `LOOP_POSITION` | 9 | 22 × 4 | entier | 0–9 une fois, 10–15 deux fois, sur les 2 × 799 patchs |
| `MASTER_BPM` | 186 | 9 | BPM direct (106 = 106 BPM) | 1-1 : 106 → 107, seul le bit 194 change (dump 4) |
| Nom | 195 | 16 × 7 | ASCII 7 bits | renommage 1-1 + 53 noms utilisateur lisibles |

Défaut usine : `BOSS ES-8       ` (751 patchs de la fixture).

`LOOP_POSITION` : 0–9 apparaissent une fois chacun, 10–15 deux fois et
s'intercalent librement entre les loops (TOC-FAT : `…6, 10, 5, 11, 3, 12…`).
Probablement des marqueurs de branches série/parallèle, à confirmer.

Carte en code : `src/es8ctl/patch.py` (`PATCH_FIELDS`).

Les champs suivent l'ordre du `.bel` (`ID_PATCH_LOOP_SW`, `ID_PATCH_LOOP_POSITION`,
…). Entre le bit 97 et le nom (195) devraient se trouver, dans l'ordre :
`MIXER_MODE`, `MIXER_GAIN1/2`, `CARRY_OVER_LOOP` (9), `INPUT/OUTPUT_SELECT/BUFFER`,
`OUTPUT_GAIN`, `CTL1–6`, `EXP1/2`, puis `MASTER_BPM` (bits 186–194, confirmé).
Les BPM des patchs utilisateur se lisent tels quels (76, 95, 105, 120…). Le
bit 185, toujours à 1, termine donc le champ précédent (`EXP2` ?).

## Questions ouvertes

1. Patch 100-8 tronqué (compteur 1615 jamais reçu, sur toutes les captures). Fin de
   dump réelle de l'ES-8 ou dernière trame perdue par l'interface ?
2. Encodage du bloc système : même empaquetage 8→7 ? Le `.bel` y décrit
   1029 valeurs.
3. Carte de bits des ~400 autres champs de patch.

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
Prochaines expériences, sur le patch 1-1, en prenant chaque fois le dump
précédent comme référence :

| # | Changement | Ce que ça révèle |
|---|---|---|
| ~~1~~ | ~~Nom → `AAAAAAAAAAAAAAAA`~~ | fait : nom décodé |
| ~~2~~ | ~~Loop 1 ON ↔ OFF~~ | fait : bit 0 |
| ~~2b~~ | ~~Loop V ON ↔ OFF~~ | fait : bit 8 → `LOOP_SW` = bits 0–8 |
| ~~3~~ | ~~Master BPM 106 → 107~~ | fait : 9 bits, bits 186–194 |
| 4 | Ordre des loops : échanger les deux premières | table `LOOP_POSITION` (22 valeurs) |
| 5 | CTL1 de la fonction OFF → une autre | `CTL_FUNC` (16 entrées) |
| 6 | Même changement que #2 sur le patch 1-2 | confirme l'indépendance des patchs |
| 7 | Un réglage système (ex. contraste LCD) | encodage du bloc système |

Raccourci majeur : si l'éditeur officiel peut **sauvegarder un `.bel`** de
l'état courant, le faire dans le même état qu'un dump SysEx. On obtient une
paire (valeurs connues ↔ bits) pour 800 patchs, et l'inférence de la carte
devient en grande partie automatique.
