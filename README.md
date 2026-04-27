# Babyfoot ENSAE

Application Flask locale pour gérer un classement babyfoot ENSAE en 1v1 et 2v2.

## Lancer en local

```bash
python -m pip install -r requirements.txt
python app.py --seed
python app.py
```

Ouvrir ensuite `http://127.0.0.1:5000`.

## Déploiement Render

Render doit installer `requirements.txt`, puis lancer:

```bash
gunicorn app:app
```

Le fichier `runtime.txt` force Python `3.11.9`, plus stable que la version par défaut de Render.

## Comptes de démo

Tous les comptes de démo utilisent le mot de passe `password123`.

- `alice.martin@ensae.fr`
- `bastien.durand@ensae.fr`
- `chloe.bernard@ensae.fr`
- `mehdi.moreau@ensae.fr`
- `ines.leroy@ensae.fr`
- `paul.robert@ensae.fr`

## Admin unique

Au premier lancement, l'application crée un seul compte admin à partir de `config.py` ou des variables d'environnement:

```bash
ADMIN_EMAIL=admin@ensae.fr
ADMIN_PASSWORD=AdminPassword123!
ADMIN_PSEUDO=GodMode
```

Par défaut en local:

- email: `admin@ensae.fr`
- mot de passe: `AdminPassword123!`

L'admin arrive sur `/admin` après connexion. Les pages admin couvrent dashboard, joueurs, matchs, litiges, classements, tournois, logs, paramètres et `/admin/god`.

## Fonctionnalités

- inscription avec email obligatoire en `@ensae.fr`;
- authentification Flask-Login et mots de passe hashés Werkzeug;
- matchs 1v1 avec défi, acceptation, refus, expiration après 2 minutes;
- matchs 2v2 avec invitation des trois autres joueurs, expiration après 3 minutes;
- saisie de score, validation par les participants, correction en cas de désaccord;
- annulation publique des refus, non-réponses et désaccords non résolus;
- compteur d'abus et bans temporaires progressifs entre joueurs/groupes;
- ratings Glicko-2 séparés pour 1v1 et 2v2;
- prédiction par point avant match;
- classements séparés 1v1 et 2v2;
- profils, photo de profil, statistiques et historique.
- admin unique avec logs d'actions sensibles, CSRF et God Mode.

## Notes techniques

La base SQLite est créée dans `data/babyfoot.sqlite3`. Les uploads sont stockés dans `static/uploads/`.

Le système de rating est dans `rating_system.py`. Il adapte Glicko-2 à une observation continue:

```text
s = points_marques / points_totaux
```

En 2v2, les ratings temporaires d'équipe utilisent la moyenne des ratings et une agrégation quadratique des RD.
