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
| Nom | 195 | 16 × 7 | ASCII 7 bits | renommage 1-1 + 53 noms utilisateur lisibles |

Défaut usine : `BOSS ES-8       ` (751 patchs de la fixture).

## Questions ouvertes

1. Patch 100-8 tronqué (compteur 1615 jamais reçu, sur 3 captures). Fin de
   dump réelle de l'ES-8 ou dernière trame perdue par l'interface ?
2. Encodage du bloc système : même empaquetage 8→7 ? Le `.bel` y décrit
   1029 valeurs.
3. Carte de bits des ~400 autres champs de patch.

## Protocole — dumps différentiels

**Lancer `es8ctl capture` avant de déclencher le dump au panneau**, sinon
les premières trames (le bloc système) sont perdues.

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
| 2 | Loop 1 ON ↔ OFF | bit d'un booléen, début de `LOOP_SW` (9 bits ?) |
| 3 | Master BPM 120 → 121 | champ large (max 315 → ≥ 9 bits) |
| 4 | Ordre des loops : échanger les deux premières | table `LOOP_POSITION` (22 valeurs) |
| 5 | CTL1 de la fonction OFF → une autre | `CTL_FUNC` (16 entrées) |
| 6 | Même changement que #2 sur le patch 1-2 | confirme l'indépendance des patchs |
| 7 | Un réglage système (ex. contraste LCD) | encodage du bloc système |

Raccourci majeur : si l'éditeur officiel peut **sauvegarder un `.bel`** de
l'état courant, le faire dans le même état qu'un dump SysEx. On obtient une
paire (valeurs connues ↔ bits) pour 800 patchs, et l'inférence de la carte
devient en grande partie automatique.
