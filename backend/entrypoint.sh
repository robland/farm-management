#!/bin/sh
set -e

# 1. Appliquer les migrations de la base de données
# python manage.py migrate --noinput

# 2. Créer le superutilisateur (le "|| true" évite une erreur si le compte existe déjà)
if [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py createsuperuser --noinput --full_name "$DJANGO_SUPERUSER_USERNAME" || true
fi
echo "Hello WORld"
# 3. Lancer le serveur principal (ex: Gunicorn)
exec "$@"
