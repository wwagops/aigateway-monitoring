FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dépendances d'abord (cache de build)
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Migrations
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8080

# La config est montée à l'exécution (volume) ou fournie via env AIGW_*.
ENTRYPOINT ["aigw-monitor"]
CMD ["run", "--config", "/app/config.yaml"]
