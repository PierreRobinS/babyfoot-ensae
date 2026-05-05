# Babyfoot ENSAE

Application Flask pour gérer un classement babyfoot ENSAE en 1v1 et 2v2.

## Lancer en local

```bash
python -m pip install -r requirements.txt
python app.py --seed
python app.py
```

Ouvrir ensuite `http://127.0.0.1:5000`.

## Déploiement PythonAnywhere

PythonAnywhere est adapté pour une version simple de ce projet:

- il sait héberger une app Flask WSGI;
- le dossier `/home/<username>/...` est persistant;
- la base SQLite `data/babyfoot.sqlite3` ne sera pas écrasée à chaque reload;
- le serveur WSGI reste géré par PythonAnywhere, donc pas besoin de `gunicorn`.

### 1. Cloner le repo

Dans une console Bash PythonAnywhere:

```bash
cd ~
git clone https://github.com/PierreRobinS/babyfoot-ensae.git
cd babyfoot-ensae
```

### 2. Créer un virtualenv

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Initialiser la base

```bash
python app.py --seed
```

Cette commande crée `data/babyfoot.sqlite3` et ajoute les comptes de démo.

### 4. Créer l'app Web

Dans l'onglet **Web** de PythonAnywhere:

1. **Add a new web app**
2. choisir **Manual configuration**
3. choisir Python `3.11`
4. renseigner le virtualenv:

```text
/home/<username>/babyfoot-ensae/.venv
```

### 5. Configurer le fichier WSGI

Dans le fichier WSGI PythonAnywhere, mets:

```python
import os
import sys

PROJECT_DIR = "/home/<username>/babyfoot-ensae"

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.environ.setdefault("DATA_DIR", os.path.join(PROJECT_DIR, "data"))
os.environ.setdefault("UPLOAD_FOLDER", os.path.join(PROJECT_DIR, "static", "uploads"))
os.environ.setdefault("SECRET_KEY", "change-moi-en-une-longue-valeur-secrete")
os.environ.setdefault("ADMIN_EMAIL", "admin@ensae.fr")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("ADMIN_PSEUDO", "GodMode")

from app import app as application
```

Remplace `<username>` par ton pseudo PythonAnywhere.

### 6. Static files

Dans l'onglet **Web > Static files**:

```text
URL:       /static/
Directory: /home/<username>/babyfoot-ensae/static/
```

### 7. Reload

Clique **Reload** dans l'onglet Web.

Teste ensuite:

```text
https://<username>.pythonanywhere.com/healthz
```

Réponse attendue:

```json
{"ok": true, "service": "babyfoot-ensae"}
```

## Mettre à jour sans écraser la base

Sur PythonAnywhere:

```bash
cd ~/babyfoot-ensae
git pull
source .venv/bin/activate
pip install -r requirements.txt
python -c "import app; print('migration ok')"
```

Puis clique **Reload** dans l'onglet Web.

Important: ne supprime pas le dossier `data/`, il contient la base SQLite.

## Comptes de démo

Tous les comptes de démo utilisent le mot de passe `password123`.

- `alice.martin@ensae.fr`
- `bastien.durand@ensae.fr`
- `chloe.bernard@ensae.fr`
- `mehdi.moreau@ensae.fr`
- `ines.leroy@ensae.fr`
- `paul.robert@ensae.fr`

## Admin unique

Au premier lancement, l'application crée un seul compte admin à partir des variables d'environnement:

```bash
ADMIN_EMAIL=admin@ensae.fr
ADMIN_PASSWORD=AdminPassword123!
ADMIN_PSEUDO=GodMode
```

L'admin arrive sur `/admin` après connexion.

## Fonctionnalités

- inscription avec email obligatoire en `@ensae.fr`;
- authentification Flask-Login et mots de passe hashés Werkzeug;
- matchs 1v1 et 2v2 avec invitations;
- scoring live mobile par swipe jusqu'à 10;
- validation finale des scores par les participants;
- Elo/Glicko-2 séparés 1v1 et 2v2;
- classements séparés;
- profils, photos, statistiques et historique;
- admin unique avec logs, litiges, paramètres et God Mode.

## Notes techniques

La base SQLite est créée dans `data/babyfoot.sqlite3`.
Les uploads sont stockés dans `static/uploads/`.
