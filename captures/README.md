# captures/

Dumps bruts de l'ES-8 (étape 0 du plan, cf. `PLAN.md`).

Conventions :

- `dump_<YYYYMMDD>_<HHMMSS>.syx` : trames SysEx brutes concaténées, telles que reçues.
- `dump_<YYYYMMDD>_<HHMMSS>.json` : sidecar de métadonnées (port, horodatage,
  en-têtes décodés de chaque trame, erreurs éventuelles).

Le premier dump complet de l'ES-8 est la **fixture de test n°1** du noyau :
une fois la structure confirmée, il est copié vers `tests/fixtures/` et
commité. Les dumps suivants (données personnelles de l'utilisateur) ne sont
pas committés.
