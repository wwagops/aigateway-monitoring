# aigw-monitor

Monitoring de serveurs d'inférence (**vLLM**, **LiteLLM**, et toute gateway **compatible
OpenAI**) déclarés par organisation. Pour chaque modèle, l'outil vérifie par des **appels
réels** de complétion :

- **up / down** — le modèle répond-il ?
- **tool calling** — sait-il émettre un `tool_calls` ?
- **reasoning** — expose-t-il du raisonnement (`reasoning_content` / `reasoning_tokens`) ?

Les états sont **historisés** (PostgreSQL, ou SQLite local par défaut) et exposés via une
**API REST** et un endpoint **Prometheus `/metrics`**, servis par le même daemon.

---

## Sommaire

- [Fonctionnement](#fonctionnement)
- [Stack](#stack)
- [Installation](#installation)
- [Base de données](#base-de-données)
- [Utilisation (CLI)](#utilisation-cli)
- [API REST](#api-rest)
- [Métriques Prometheus](#métriques-prometheus)
- [Configuration](#configuration)
- [Sécurité](#sécurité)
- [Déploiement Docker](#déploiement-docker)
- [Développement](#développement)
- [Contribuer](#contribuer)

---

## Fonctionnement

```
config.yaml ─┐
             ├─► loader (deep-merge capacités)  ─► [ResolvedTarget, …]
env AIGW_*  ─┘                                          │
                                                        ▼
                            runner.run_cycle (concurrence bornée)
                                   │  pour chaque cible :
                                   │   • liveness   (toujours)
                                   │   • tool_calling (si déclaré)
                                   │   • reasoning   (si déclaré)
                                   ▼
                    ┌──────────────┴───────────────┐
                    ▼                               ▼
         PostgreSQL / SQLite (hist.)        Prometheus gauges
                    ▲                               ▲
                    └──────── API REST FastAPI ─────┘   (même serveur HTTP, daemon)
```

Trois caractéristiques clés :

1. **Configuration en couches** — tout paramètre runtime est réglable via le fichier YAML
   *ou* via variable d'env `AIGW_*`. Précédence : **défauts < fichier < env**.
2. **Capacités déclarées par modèle** — on déclare les capacités attendues ; elles
   **pilotent quelles sondes tournent** (capacité non déclarée → statut `SKIPPED`). Une
   capacité déclarée disponible mais observée indisponible est signalée comme **dérive**.
3. **Surface de monitoring uniquement** — aucune clé API, aucun contenu généré, et `base_url`
   masquée par défaut dans l'API et les métriques.

---

## Stack

Python 3.11+ · pydantic / pydantic-settings · SQLAlchemy 2 (async, asyncpg / aiosqlite) · Alembic ·
httpx · APScheduler · FastAPI / uvicorn · prometheus-client · Typer · structlog.

---

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml      # adapter les cibles
cp .env.example .env                     # paramètres AIGW_* (PAS les clés API)
export ACME_API_KEY=sk-...               # clés API = vraies variables d'environnement
```

> **`.env` vs variables d'environnement** : le `.env` ne contient que les paramètres `AIGW_*`
> (lus par pydantic-settings). Les **clés API** (référencées par `api_key_env`) doivent être de
> **vraies variables d'environnement** — le `.env` n'est pas ré-exporté dans `os.environ`.
> Toute `AIGW_*` peut aussi être exportée en variable d'env (elle est alors **prioritaire** sur
> le `.env`). Précédence : `env réel > .env > bloc monitor: du YAML > défauts`.

> **Note Python 3.14** : certains binaires natifs (`asyncpg`, `uvloop`) n'ont pas toujours de
> wheel pré-compilé sur les versions très récentes de Python. En cas d'échec d'installation,
> utilisez Python 3.11–3.12 (l'image Docker fournie est basée sur 3.12).

---

## Base de données

L'URL est lue depuis les Settings (bloc `monitor:` du YAML ou `AIGW_DATABASE_URL`).

### SQLite (défaut, local / dev) — zéro configuration

Si **aucune URL n'est fournie**, l'outil utilise une base **SQLite locale**
(`sqlite+aiosqlite:///aigw.db`) et **crée le schéma automatiquement** au démarrage.
Aucune migration Alembic n'est nécessaire — `aigw-monitor run` / `check-once` fonctionnent
directement. Idéal pour tester ou un usage léger mono-process.

```bash
aigw-monitor run -c config.yaml          # crée ./aigw.db et démarre
```

### PostgreSQL (production)

Fournir une URL PostgreSQL et appliquer les migrations Alembic (qui créent les tables
`check_runs` / `model_checks`, le type enum natif `liveness_status` et la colonne JSONB
`capabilities`) :

```bash
docker compose up -d postgres            # ou un PostgreSQL existant
export AIGW_DATABASE_URL=postgresql+asyncpg://aigw:aigw@localhost:5432/aigw
alembic upgrade head
```

> Les migrations Alembic sont **spécifiques à PostgreSQL** (enum natifs, JSONB). En SQLite, le
> schéma est créé via `create_all` au lieu d'Alembic — ne lancez pas `alembic upgrade` sur SQLite.

---

## Utilisation (CLI)

```bash
# Valider la config et voir les sondes sélectionnées par modèle
aigw-monitor validate-config -c config.yaml

# Exécuter un seul cycle (résumé lisible + persistance)
aigw-monitor check-once -c config.yaml
aigw-monitor check-once -c config.yaml --no-store   # sans écrire en base
aigw-monitor check-once -c config.yaml --verbose    # logs détaillés (INFO) sur stderr

# Lancer le daemon (scheduler + API REST + /metrics)
aigw-monitor run -c config.yaml
```

`check-once` affiche un **tableau** (une colonne par capacité, cellule = `statut latence`) —
bordé et coloré en terminal, aligné sans bordures en pipe :

```
  aristote  gpt-oss-120b   UP 244ms   AVAILABLE 479ms  AVAILABLE 1313ms
  aristote  llama-3.1-8b   UP 263ms   ERROR 240ms      UNAVAILABLE 1836ms   ⚠ dérive: reasoning
  aristote  unknown-model  DOWN 56ms  —                —
```

Suit une section **« Détails par sonde »** : pour chaque sonde exécutée, la requête envoyée
(`↳ prompt / outil / extra_body`, y compris pour les sondes OK) et, pour les non-OK, le code
HTTP + le message d'erreur. Les logs vont sur **stderr** (stdout = tableau seul, pipe-friendly) ;
`--verbose` ajoute les logs INFO.

---

## API REST

Servie sur `api_port` (def. 8080), en lecture seule :

| Méthode & route | Description |
|---|---|
| `GET /health` | santé du monitor (DB, dernier run, nb de cibles) |
| `GET /api/organizations` | organisations configurées |
| `GET /api/models` | cibles + capacités déclarées + sondes sélectionnées |
| `GET /api/status?org=&model=` | **état courant** (par modèle : up/down `liveness_status` + `liveness_probe` (nom de la sonde : `chat_completion`/`list_models`) + latence + `http_status`/`error` ; par capacité `{status, latency_ms, http_status, error, request}` — `request` = log d'entrée : prompt/outil/extra_body) |
| `GET /api/models/{org}/{model}/history?since=&until=&limit=` | historique paginé |
| `GET /api/runs` · `GET /api/runs/{id}` | cycles de checks et leur détail |
| `GET /metrics` | exposition Prometheus (répond 200 directement) |

```bash
curl localhost:8080/api/status | jq
curl localhost:8080/metrics
```

Doc OpenAPI interactive : `http://localhost:8080/docs`.

---

## Métriques Prometheus

Labels `org` / `model` (+ `capability`/`probe` descriptifs) ; jamais de `base_url` ni de secret :

| Métrique | Type | Description |
|---|---|---|
| `aigw_model_up` | gauge | 1 si up, 0 sinon (label `probe` = sonde up/down : `chat_completion`/`list_models`) |
| `aigw_model_capability_available` | gauge | 1/0 par capacité (label `capability`) ; absente si non testée |
| `aigw_model_check_latency_seconds` | gauge | latence de la sonde up/down (label `probe`) |
| `aigw_model_check_errors_total` | counter | nombre de checks en erreur |
| `aigw_model_capability_mismatch` | gauge | dérive déclaré vs observé (label `capability`) |
| `aigw_check_run_timestamp_seconds` | gauge | horodatage du dernier cycle |
| `aigw_check_run_duration_seconds` | gauge | durée du dernier cycle |

---

## Configuration

Un **seul fichier YAML** porte deux blocs : `monitor:` (runtime) et `defaults:` +
`organizations:` (cibles). Voir [`config.example.yaml`](config.example.yaml).

```yaml
monitor:
  # database_url omis → SQLite local auto (sqlite+aiosqlite:///aigw.db). Sinon : URL PG.
  # database_url: postgresql+asyncpg://aigw:aigw@localhost:5432/aigw   # ou env AIGW_DATABASE_URL
  schedule: 60                 # « écart » entre passages de sonde : secondes (int) OU cron (str)
  http_timeout_seconds: 30
  max_concurrency: 16
  api_host: 0.0.0.0
  api_port: 8080
  metrics_path: /metrics
  expose_base_url: false       # masque les base_url internes dans l'API / metrics
  log_level: INFO

defaults:                      # fallback global, hérité par toutes les cibles
  max_tokens: 16
  capabilities:
    tool_calling: false
    reasoning: false

model_defaults:                # capacités PAR NOM DE MODÈLE, valables dans TOUTES les orgs
  gpt-oss-120b:
    capabilities: { tool_calling: true, reasoning: true }
  deepseek-r1:
    capabilities:
      tool_calling: true
      reasoning: { enabled: true, extra_body: { chat_template_kwargs: { enable_thinking: true } } }

organizations:
  - name: acme
    base_url: https://gateway.acme.internal/v1
    api_key_env: ACME_API_KEY  # NOM d'une variable d'env (jamais la clé en clair)
    capabilities: { tool_calling: true }   # défaut org, hérité par ses modèles
    models:
      - name: qwen2.5-72b-instruct         # tool_calling via le défaut d'org
      - name: deepseek-r1                  # tool + reasoning via model_defaults (non répété)
      - name: gpt-oss-120b
        capabilities: { reasoning: false } # override (org, modèle) : désactive le reasoning ici
  - name: research
    base_url: https://llm.research.internal/v1
    api_key_env: RESEARCH_API_KEY
    models:
      - name: gpt-oss-120b                 # même modèle, autre org : hérite de model_defaults
      - name: mistral-small-3.2-24b        # hors registre + aucune capa → liveness seulement
```

### Précédence des paramètres runtime

`défauts du champ` **<** bloc `monitor:` du YAML **<** variables d'environnement `AIGW_*`.

Variables d'env reconnues : `AIGW_CONFIG_PATH`, `AIGW_DATABASE_URL`, `AIGW_SCHEDULE`,
`AIGW_HTTP_TIMEOUT_SECONDS`, `AIGW_MAX_CONCURRENCY`, `AIGW_API_HOST`, `AIGW_API_PORT`,
`AIGW_METRICS_PATH`, `AIGW_EXPOSE_BASE_URL`, `AIGW_LOG_LEVEL`.

### Capacités → sélection des sondes

Les capacités d'une cible `(organisation, modèle)` sont fusionnées selon une précédence
**du moins au plus spécifique** :

```
defaults.capabilities  <  org.capabilities  <  model_defaults[<nom>]  <  org.models[i].capabilities
   (tout le monde)         (toute l'org)        (ce modèle, toutes orgs)     (cette cible précise)
```

- **`model_defaults`** déclare les capacités intrinsèques d'un modèle **une seule fois** et les
  applique à ce modèle dans **n'importe quelle organisation** (sans répétition). Il **prime sur
  le défaut d'org** et n'est surchargé que par une déclaration explicite `(org, modèle)`.
- `liveness` tourne **toujours** ; les capacités ne sont sondées que si déclarées
  (`true` ou `{ enabled: true }`) **et** présentes dans le registre.
- **Méthode `liveness`** (même précédence) : `chat` (chat completion réel, défaut) ou
  `models` (`GET /v1/models`, plus léger). Réglable à chaque niveau (`defaults`, `org`,
  `model_defaults`, `(org, modèle)`).
- Forme courte (`tool_calling: true`) ou objet pour passer un `extra_body` spécifique au
  provider (ex. activer le *thinking*).

> **Ajouter une capacité** (dev) : écrire une sonde + l'enregistrer dans le registre
> `CAPABILITY_PROBES` ; tout le reste suit automatiquement. Détails dans [`CLAUDE.md`](CLAUDE.md).

---

## Sécurité

- **Clés API** : référencées par `api_key_env` (nom de variable), résolues depuis l'environnement
  réel (`os.environ`) au runtime — **pas** depuis le `.env`, qui n'est pas ré-exporté. Envoyées
  dans l'en-tête `Authorization` des appels sortants. **Jamais** persistées, **jamais** renvoyées
  par l'API, **jamais** en label Prometheus.
- **Contenu généré** : non stocké. On ne garde que des **statuts**, latences, codes HTTP.
- **`base_url`** (infra interne) : absente des métriques, masquée dans l'API par défaut
  (`expose_base_url: false`).
- **`error` / `details`** : assainis (base_url remplacée par `<endpoint>`, troncature).

---

## Déploiement Docker

```bash
cp config.example.yaml config.yaml && cp .env.example .env
docker compose up --build       # postgres + migrations + monitor (API sur :8080)
```

`docker-compose.yaml` enchaîne trois services : `postgres`, `migrate` (applique
`alembic upgrade head` puis se termine), puis `monitor`.

---

## Développement

```bash
pip install -e ".[dev]"
pytest            # 18 tests : sondes (respx), config/précédence + model_defaults,
                  #            fallback SQLite, API + DB (sqlite/ASGITransport)
ruff check .
mypy src
```

Voir [`CLAUDE.md`](CLAUDE.md) pour la carte de l'architecture et les conventions internes.

## Contribuer

Les messages de commit suivent la convention **[Gitmoji](https://gitmoji.dev)** — voir
[`CONTRIBUTING.md`](CONTRIBUTING.md) pour le format, la table d'emojis et les règles.
