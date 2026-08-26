# Imagen unica para web y worker: el mismo codigo con distinto comando.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint (usado para los PDF) necesita las librerias de Cairo y Pango.
# Sin estas, la imagen instala pero revienta al primer PDF.
RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        libpq-dev \
        libcairo2 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Las dependencias primero: cambian mucho menos que el codigo, y asi la capa
# se reaprovecha entre builds.
COPY pyproject.toml poetry.lock ./
RUN pip install --upgrade pip poetry poetry-plugin-export \
    && poetry export --without-hashes --format requirements.txt --output /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput --settings=config.settings || true

COPY docker-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["web"]
