#!/bin/sh
# Arranque del contenedor. Espera la base, migra y levanta lo que se le pida.
set -e

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

echo "Esperando a Postgres en ${DB_HOST}:${DB_PORT}..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1; do
  sleep 1
done
echo "Postgres disponible."

case "$1" in
  web)
    # Los dos migrate_schemas son necesarios: core, assembly, wms, edge,
    # eventbus y connect viven en TENANT_APPS.
    python manage.py migrate_schemas --shared --noinput
    python manage.py migrate_schemas --tenant --noinput
    exec gunicorn config.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers "${WEB_CONCURRENCY:-3}" \
        --timeout "${WEB_TIMEOUT:-60}" \
        --access-logfile - \
        --error-logfile -
    ;;
  worker)
    # El worker no migra: si lo hiciera, dos procesos correrian migraciones a la vez.
    exec python manage.py run_huey
    ;;
  *)
    exec "$@"
    ;;
esac
