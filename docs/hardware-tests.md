# Comportements de l'ES-8 vérifiés sur l'appareil, et ce qui reste à voir

Chaque ligne indique si on peut la tester sans écrire (🟢), en écrivant sur une
banque sacrifiable (✍️), et si quelqu'un doit regarder la pédale ou appuyer
dessus (👀). Les questions propres aux rigs, à la Companion et à l'hôte de
scène sont suivies dans ES8 Stage (`jpecquais/es8-stage`).

## Switches, assignations et LED (séance du 2026-10-20, patch sonde 97-1)

- **Mode manuel** : NUM1–8 ne font que commuter des boucles (`manual_number` : 0 = AUTO, la
  boucle du même numéro ; 1–8, V = une autre). Aucune assignation ne part, quelle que soit
  la fonction (`ctl_func` système ignoré pour les NUM). Doc BOSS v2, « Number 1–8 (MAN) ».
- **Mode memory** : un NUM dont la fonction du patch n'est plus `NUM_x` (OFF, CTL_x…) ne
  rappelle plus de patch et ses assignations partent. MOM : max à l'appui, min au
  relâchement ; MOM avec min = max : un cran fixe à chaque appui ; TGL : max puis min.
- **LED** : la cible `LED_NUMx` marche en memory. Un switch en OFF n'allume pas sa LED tout
  seul : TGL `LED_NUMx` 0/1 sur lui-même la fait suivre. MOM 1/1 l'allume (sans jamais
  l'éteindre). MOM 0/0 vers la LED d'un autre switch l'a basculée plutôt qu'éteinte
  (observé, à confirmer). Une fonction CTL_x (même en TGL) n'allume pas la LED du switch.
- **Pas de groupes exclusifs natifs** : les cibles CTL1–6 n'agissent pas sur les autres
  switches (sorties CTL OUT), et chaque assignation TGL garde son propre état. La source
  d'assignation CTL1–4 est la prise CTL IN (doc BOSS v2).
- La fonction d'un switch vient du patch ou du système (Preference PAT/SYS, `ctl_sw`) ;
  les assignations sont toujours celles du patch courant.
- **Bascule TGL et rappel de patch** : au rappel, la LED part de `led_numX` du patch, mais la
  bascule de l'assignation repart de off (le premier appui envoie MAX). Parade vérifiée : dans
  un patch où le paramètre est on, inverser l'assignation (MIN = haut, MAX = bas ; LED MIN = 1,
  MAX = 0) et `led_numX` = 1.

## Commandes de l'éditeur

Balayage des commandes `7F00`–`7F7F` inconnues (2026-10-20, DT1 de 2 octets en mode
éditeur, donnée = n° du patch sonde, sauvegarde complète avant) : aucune réponse SysEx, rien
d'autre de changé que le patch visé. **`7F02` = initialiser le patch n** (comme `7F21`) :
à ne jamais envoyer. Aucune commande LED côté logiciel ; l'éditeur officiel n'en a pas.

## MIDI

- **MIDI OUT en Thru** : les messages des patchs sortent dans les deux modes ; Thru ajoute
  l'écho de tout ce qui entre. Au changement de patch à distance, seuls les messages du patch
  sortent, jamais son numéro (le protocole de l'éditeur sait lire le patch en cours).
- **pc_map** : un PC *i* reçu rappelle le patch de la `pc_map` (répétitions comprises) ; un PC
  sur un autre canal est ignoré ; un PC au-delà du dernier pas reste sur le dernier patch.
  Bank Select CC0 (même collé au PC) choisit la banque MIDI ; CC32 est ignoré.
- `midi_pc` = 0 n'envoie aucun PC (le CC part seul). Le PC d'un patch repart à chaque rappel ;
  rappeler le patch déjà chargé n'émet rien.

## Ouvert

| # | Question | Type | État |
|---|---|---|---|
| S1 | Ce que fait l'ES-8 d'une demi-page (écriture coupée entre les deux messages d'une page) | ✍️ | simulé seulement |
| S2 | Champs déduits : `mixer_*`, `midi_clock_out`, `midi_transmit`, extension système v2, affichage des parallèles 13–15 | ✍️ 👀 | ouvert |
| S3 | Retours stéréo des loops 7/8 et nombre de mixers qui en dépend | ✍️ 👀 | ouvert |
| S4 | `manual_number` = OFF : encodage | ✍️ 👀 | ouvert |
| S5 | La source d'assign « CC reçu » écoute-t-elle sur le canal de réception système ? | ✍️ | ouvert |
| S6 | `MEM_U` / `MEM_D` passent-ils d'une banque à la suivante ? | 👀 | ouvert |
| S7 | Un PC reçu en mode manuel est-il suivi ? | 👀 | ouvert |
