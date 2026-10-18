# Contrat agent — piloter l'ES-8 avec `es8ctl`

À l'intention d'un agent (LLM) ou d'un script. **L'agent n'accède qu'au
CLI, jamais au MIDI directement.** Toutes les écritures passent par
`es8ctl apply`, qui valide, simule, sauvegarde et n'envoie qu'avec `--write`.

## Principes

- Sortie JSON sur stdout ; progression et rappels sur stderr.
- Codes de sortie déterministes : `0` succès, `1` écart constaté
  (`diff`, `verify`, `check`), `2` entrée invalide (rien n'est envoyé),
  `3` écriture interrompue (partielle — re-dumper et vérifier).
- Patchs nommés comme sur l'écran : `0-1` … `99-8` (banque 0–99, numéro 1–8).
- Valeurs : forme du `.bel` de l'éditeur officiel (entier, liste, ou chaîne
  pour `name`). Index et valeurs symboliques acceptés par `transform set`
  (`ctl_func[NUM_8]=BPM`, `loop_sw[L6]=1`).
- Chaîne de loops en notation écran : `loop_chain`, ex. `V8746(3//5)21`
  (`V` = loop volume, `1`–`8` = loops, `(a//b)` = parallèle).

## Ce que l'agent ne peut pas faire seul

- **Garantir la réception** : après un dump, l'ES-8 reste sur l'écran Bulk
  Dump où il **ignore sans erreur** tout ce qu'il reçoit. Avant toute
  écriture, demander à l'humain d'appuyer sur EXIT (écran de jeu).

Lire l'appareil ne demande aucun geste : `es8ctl read` l'interroge à distance.

## Boucle type

```sh
es8ctl read --port "WIDI Jack Bluetooth"             # état actuel → captures/read_*.syx
es8ctl patches captures/<dump>.syx -p 0-8            # lire
es8ctl transform set "master_bpm=120" -b captures/<dump>.syx --patches 0-1..0-8 -o changes.json
es8ctl apply changes.json -b captures/<dump>.syx     # simulation : lire "changes"
es8ctl apply changes.json -b captures/<dump>.syx --write --port "WIDI Jack Bluetooth" --confirm
# --confirm relit et renvoie les pages perdues ; "confirmed": true = enregistré
es8ctl read --port "WIDI Jack Bluetooth"             # facultatif : relecture complète
es8ctl check changes.json captures/<nouvelle lecture>.syx  # 0 = tout est appliqué
```

## Commandes

| Commande | Rôle | Entrée → sortie |
|---|---|---|
| `devices` | ports MIDI | → `{input_ports, output_ports}` |
| `read` | lire l'appareil à distance | port → `.syx` (complet ou partiel) ; code 1 si des pages manquent |
| `capture` | enregistrer un dump déclenché au panneau | port → `.syx` + sidecar |
| `patches` | lire des patchs | `.syx` [`-p 0-1`] → `{patches: [{patch, …champs, loop_chain}]}` |
| `system` | lire le système | `.syx` → `{system: {…}}` |
| `diff` | comparer deux dumps | → plages de bits par patch |
| `transform set` / `swap-loops` / `variants` | préparer des changements | `.syx` → changements JSON |
| `import-bel` / `export-bel` | interop. éditeur officiel | `.bel` ⇄ changements / `.syx` → `.bel` |
| `apply` | écrire | changements + `.syx` de base → plan ; `--write` envoie |
| `verify` | dump attendu = dump réel ? | ignore le patch sélectionné (`current_num`) |
| `check` | changements présents dans un dump ? | par patch : `applied`, `mismatches` |

## Format des changements

```json
{
  "patches": {"0-8": {"master_bpm": 99, "name": "MY PATCH        ",
                      "loop_chain": "V8746(3//5)21"}},
  "system": {"others_lcd_contrast": 5}
}
```

Seuls les champs fournis changent ; tous les autres bits (y compris non
cartographiés) sont repris du dump de base. Champ inconnu ou valeur hors
bornes → code 2, rien n'est envoyé.

## Règles de sûreté (non négociables)

1. Toujours partir d'un dump **frais** : la base doit refléter l'appareil.
2. Toujours simuler avant `--write`, et montrer les `changes` à l'humain
   pour toute écriture de masse.
3. Toujours vérifier après écriture (`--confirm`, ou `read` + `check`) :
   sans `--confirm`, un code 0 de `apply` signifie « envoyé », pas
   « enregistré ».
4. Ne jamais supprimer `backups/` ni réécrire un fichier de `captures/`.
