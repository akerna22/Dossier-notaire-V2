# Dossier parcellaire et urbanistique (v2)

Site local ou hébergé (Render) : recherche d'adresse, carte interactive IGN, sélection de plusieurs parcelles au clic,
estimation du prix au m² (DVF) et PDF global ou par thème (cadastre, urbanisme, risques, environnement, littoral/mérule, estimation).

## Lancer en local
Windows : double-clic sur `lancer.bat` · Mac/Linux : `./lancer.sh` · puis http://127.0.0.1:5000

## Render (gratuit)
Build : `pip install -r requirements.txt` · Start : `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180`
Variables : `PYTHON_VERSION=3.12.3`, `APP_PASSWORD=<mot de passe>`.

## GitHub Actions (sans serveur)
Onglet Actions > « Générer un dossier parcellaire » > Run workflow : PDF global pour une adresse (parcelle au point d'adresse).

## Fichiers
`sources.py` (API de l'État) · `maps.py` (cartes du PDF) · `report.py` (PDF) · `app.py` + `templates/index.html` (site) · `generate.py` (ligne de commande).
