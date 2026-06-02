# CLAUDE.md

Guide pour les agents Claude Code travaillant sur ce dépôt. Lis-le avant de modifier le code.

## Objectif

`aigw-monitor` surveille des serveurs d'inférence **compatibles OpenAI** (vLLM, LiteLLM, …)
déclarés par organisation. Pour chaque modèle il fait des **appels réels** et détermine :
**up/down**, **tool calling** dispo, **reasoning** dispo. États historisés en PostgreSQL
(ou SQLite local par défaut), exposés via **API REST** + **Prometheus** (un seul serveur HTTP, dans le daemon).

## Commandes

```bash
source .venv/bin/activate                 # venv déjà présent (gitignored)
pip install -e ".[dev]"                    # deps complètes
pytest                                     # 18 tests, ~0.2s (sqlite + respx, pas de PG requis)
ruff check .                               # lint  — DOIT rester clean
mypy src                                   # types — DOIT rester clean
aigw-monitor validate-config -c config.yaml
aigw-monitor check-once     -c config.yaml --no-store
aigw-monitor run            -c config.yaml
```

Avant de conclure une tâche : `ruff check . && mypy src && pytest` doivent tous passer.

**Commits** : convention **Gitmoji** (`<emoji> [(scope)] <sujet à l'impératif>`) — voir
[`CONTRIBUTING.md`](CONTRIBUTING.md). Conserver le trailer `Co-Authored-By:` sur les commits assistés.

## Carte de l'architecture (`src/aigw_monitor/`)

| Module | Rôle |
|---|---|
| `settings.py` | `Settings(BaseSettings)` runtime. Précédence : **défauts < bloc `monitor:` du YAML < env `AIGW_*`** via `settings_customise_sources` + `YamlMonitorSource`. Défaut `database_url` = **SQLite local** ; `is_sqlite` expose le dialecte. |
| `config/schema.py` | Schémas Pydantic du YAML (`CapabilitySpec`, `Capabilities`, `OrgEntry`, `RootConfig`). `extra="forbid"` pour attraper les fautes de frappe. |
| `config/loader.py` | YAML → `list[ResolvedTarget]`. **Deep-merge des capacités** (voir précédence ci-dessous), résolution `api_key_env`→env, `ResolvedTarget.enabled_capabilities`. (La sélection des sondes vit dans `checks/capabilities.selected_probes`.) |
| `checks/result.py` | Enums `LivenessStatus` / `CapabilityStatus` (`StrEnum`) + `ProbeResult`. |
| `checks/client.py` | Wrapper httpx async ; POST sur **URL absolue** `{base_url}/chat/completions`. |
| `checks/probes.py` | `check_liveness` + une sonde par capacité (`check_tool_calling`, `check_reasoning`, …). Mapping réponse→statut. |
| `checks/capabilities.py` | **Point d'extension** : registre `CAPABILITY_PROBES` (nom→sonde) + `CAPABILITY_NAMES` + `selected_probes(target)`. Ajouter une capacité = 1 sonde + 1 entrée ici. |
| `checks/runner.py` | `run_cycle()` : concurrence bornée (`Semaphore`), **itère le registre** → `ModelCheckResult.capabilities: dict[str, ProbeResult]`, détection de dérive, persistance + métriques. |
| `db/base.py`,`db/models.py`,`db/repository.py` | Moteur async, init schéma SQLite (`create_all_if_sqlite`), ORM (`CheckRun`,`ModelCheck` — capacités en **colonne JSONB générique**), requêtes. |
| `metrics/prometheus.py` | `PrometheusMetrics` (registre dédié) ; gauge **générique** `aigw_model_capability_available` (label `capability`) ; `aigw_model_up`/`aigw_model_check_latency_seconds` portent un label `probe` (nom de la sonde up/down). |
| `api/` | FastAPI lecture seule (`routes.py`, `schemas.py`, `deps.py`, `app.py`). |
| `scheduler.py`,`service.py`,`cli.py` | Trigger APScheduler, daemon (uvicorn+scheduler), CLI Typer. |

## Conventions & invariants à NE PAS casser

- **Import paresseux checks↔db** : `runner.run_cycle` importe `save_run` **dans la fonction**
  (`from ..db.repository import save_run`) pour éviter un cycle d'imports
  (`checks/__init__` → runner → db → `checks.result`). Ne pas remonter cet import au top-level.
- **`/metrics` est une route explicite** (`app.add_route`) et **pas** `app.mount()` : le mount
  Starlette imposait un `307` vers `/metrics/`. Garder la route explicite (répond `200`).
- **Logs → stderr, stdout = sortie produit** : `configure_logging` (logging.py) envoie structlog
  + stdlib sur **stderr** ; les tableaux CLI (`typer.echo`) vont sur **stdout** (pipe-friendly).
  Les commandes humaines (`check-once`, `validate-config`) configurent les logs à **WARNING**
  (donc pas de bruit httpx/INFO) ; `check-once --verbose` repasse à INFO. Le daemon (`run`)
  garde `settings.log_level`. Ne pas logger sur stdout ni baisser ce niveau par défaut.
- **Tableau CLI** : bordé (filets pleins) + couleurs via **rich** si `sys.stdout.isatty()`
  (`_print_table_rich`), sinon aligné par espaces sans bordures (`_print_table_plain`,
  pipe-friendly). Garder cette bascule TTY.
- **Portabilité DB (tests sqlite)** : utiliser `JSON_VARIANT` (= `JSON().with_variant(JSONB(),
  "postgresql")`) et `SAEnum` (type nommé `_liveness_enum`). Les statuts de capacité sont dans
  la **colonne JSONB `capabilities`** (pas de colonne/enum par capacité). Pas de SQL PG-only
  (ex. `DISTINCT ON`).
- **« État courant » = lignes du dernier run terminé** (`repository.get_current_status` via
  `latest_completed_run_id`), car chaque cycle couvre **toutes** les cibles. Si tu introduis des
  runs partiels, cette hypothèse tombe — adapter la requête.
- **Ajouter une capacité = 2 endroits** : écrire `check_x()` dans `probes.py`, l'enregistrer
  dans `CAPABILITY_PROBES` (`checks/capabilities.py`). Tout le reste (runner, JSONB, métrique
  `capability`, API `capabilities`, colonnes CLI) **itère le registre** → rien d'autre à toucher,
  pas de migration (JSONB).
- **Capacités → sondes** : `liveness` toujours ; une capacité n'est sondée que si `enabled`
  **et** présente dans le registre. Sonde non lancée ⇒ statut `SKIPPED`. Logique :
  `checks.capabilities.selected_probes(target)` (fonction libre) + `runner._check_target`.
- **Précédence de fusion des capacités** (du moins au plus spécifique), dans
  `loader.load_config` :
  `defaults.capabilities` **<** `org.capabilities` **<** `model_defaults[<nom>]` **<**
  `org.models[i].capabilities`. Le registre `model_defaults` (clé = nom de modèle) s'applique
  à ce modèle dans **toutes** les organisations et **prime sur le défaut d'org** ; seul un
  override explicite `(org, modèle)` le surclasse. Même précédence pour `max_tokens`
  (helper `_first_not_none`). Ne pas réordonner sans mettre à jour `test_config.py` et le README.
- **Méthode liveness** (`ResolvedTarget.liveness`, `Literal["chat","models"]`) : résolue avec la
  **même précédence** (`defaults.liveness` vaut `chat`, donc toujours défini). `check_liveness`
  dispatche vers `_liveness_via_chat` (chat completion réel, défaut) ou `_liveness_via_models`
  (`client.list_models()` → `GET /v1/models`, `UP` si le modèle figure dans `data[].id`). La
  méthode est reflétée dans `probe_request("liveness", …)` (`{endpoint: "GET /v1/models", …}`
  pour `models`).
- **Nom de la sonde up/down** : la liveness est **nommée comme une capacité** selon sa méthode
  via `probes.liveness_name(method)` (`LIVENESS_PROBE_NAMES` : `chat`→`chat_completion`,
  `models`→`list_models`). Porté par `ModelCheckResult.liveness_name`, listé dans
  `validate-config` (colonne SONDES, à côté de `tool_calling`/`reasoning`) et la section
  « Détails par sonde » de la CLI, **persisté** dans `details.liveness_probe`, exposé par l'API
  (`ModelStatusOut.liveness_probe`) et mis en **label `probe`** sur `aigw_model_up` /
  `aigw_model_check_latency_seconds`. Ajouter une méthode liveness = 1 entrée dans
  `LIVENESS_PROBE_NAMES` + le dispatch dans `check_liveness`/`probe_request`.
- **Dérive** : capacité déclarée `enabled=true` mais sonde `UNAVAILABLE` ⇒ ajoutée à
  `mismatches` (et gauge `aigw_model_capability_mismatch`). Voir `runner._detect_mismatches`.

## Sémantique des statuts

- Liveness : `UP` (chat : 200 + `choices` ; models : modèle listé dans `/v1/models`) ·
  `DOWN` (HTTP non-200 / JSON invalide / modèle absent de la liste) · `ERROR`
  (réseau/timeout) · `SKIPPED`.
- Capacité : `AVAILABLE` · `UNAVAILABLE` · `ERROR` · `SKIPPED`. Les gauges Prometheus de
  capacité ne sont émises que pour `AVAILABLE`/`UNAVAILABLE`.

## Logs essentiels par sonde (entrée + sortie)

Chaque `ProbeResult` porte la **sortie** (`status`, `latency_ms`, `http_status`, `error`) **et**
l'**entrée** (`request` : prompt/outil/`extra_body`, reconstruite par `probes.probe_request`
depuis des **constantes partagées** — `LIVENESS_PROMPT`/`TOOL_PROMPT`/`REASONING_PROMPT` — pour
éviter toute dérive, et attachée par le runner). Persistés dans le JSONB `capabilities`
(+ `details.liveness`), affichés dans la section « Détails par sonde » de la CLI (entrée
`request` pour **toutes** les sondes exécutées, sortie HTTP/erreur pour les non-OK) et exposés
par `CapabilityOut` de l'API (`latency_ms`, `http_status`, `error`, `request`). Erreurs **assainies**.
Dans la CLI, la sonde up/down y apparaît sous son **nom** (`liveness_name`, ex. `chat_completion`),
au même titre que les capacités.

## Détection des capacités (champs validés sur un vrai endpoint)

- **tool calling** : présence de `choices[0].message.tool_calls` (forme OpenAI standard). Un
  `400` « tools not supported » ⇒ `UNAVAILABLE`.
- **reasoning** : `message.reasoning_content` **ou** `message.reasoning` non vide, **ou**
  `usage.completion_tokens_details.reasoning_tokens > 0`. Détection **heuristique et
  dépendante du provider** ; les déclencheurs spécifiques passent par `capabilities.<cap>.
  extra_body` (fusionné dans le corps de la requête). Valider tout changement contre un vrai
  serveur de reasoning.

## Base de données & migrations

- **Défaut = SQLite local** (`Settings.database_url` = `sqlite+aiosqlite:///aigw.db`). Si l'URL
  est SQLite, `create_all_if_sqlite(engine)` (dans `db/base.py`) crée le schéma via
  `Base.metadata.create_all` — **appelé au démarrage du daemon et dans `check-once --store`**.
  Donc pas d'Alembic en SQLite. `Settings.is_sqlite` expose le test de dialecte.
- **PostgreSQL (prod)** : fournir `AIGW_DATABASE_URL=postgresql+asyncpg://…` puis
  `alembic upgrade head`. `create_all_if_sqlite` est un **no-op** hors SQLite (le schéma reste
  géré par Alembic).
- Alembic : `migrations/env.py` **async**, URL issue de `Settings().database_url`. Migrations
  **écrites à la main** (PG : `postgresql.ENUM` + `JSONB`) — elles ne tournent **pas** sur SQLite.
  `0001_initial` (tables + enums), `0002_capabilities_jsonb` (colonne JSONB `capabilities`, drop
  des colonnes par capacité + type `capability_status`). Ajouter une **capacité** ne demande
  **aucune** migration (JSONB) ; une nouvelle **colonne** oui (autogenerate nécessite un PG vivant).
- Les **tests** utilisent `create_all` sur sqlite : tout nouveau modèle doit rester compatible
  sqlite (`JSON_VARIANT`, `SAEnum`, pas de SQL PG-only).

## Tests

`tests/` : sqlite en mémoire (`StaticPool`, fixture `session_factory`), `respx` pour mocker les
réponses OpenAI, `httpx.ASGITransport` pour appeler l'API sans serveur. Pas de PostgreSQL ni de
réseau requis. Ajoute un test pour tout nouveau comportement (mapping de sonde, route API,
règle de config).

## Sécurité (à respecter dans tout code/log)

- Ne jamais logger, échoer, ni écrire dans un fichier une clé API / token.
- Les clés ne transitent que via `api_key_env` → **`os.environ`** (vraies variables d'env, **pas**
  le `.env`) → header `Authorization`. Pas en base, pas dans l'API, pas dans les labels Prometheus.
  Assainir `base_url` dans les messages d'erreur.

## Pièges connus

- **Python 3.14** : `asyncpg`/`uvloop` peuvent ne pas avoir de wheel ⇒ préférer 3.11–3.12
  (Docker = 3.12). Le venv local a été monté en évitant les drivers natifs pour les tests.
- `AIGW_SCHEDULE` (env, donc `str`) est normalisé en `int` si numérique (validateur dans
  `settings.py`) ; sinon traité comme expression cron.
- **`.env`** est lu par pydantic-settings pour les `AIGW_*` mais **n'est pas exporté dans
  `os.environ`**. Conséquence : les clés `api_key_env` (résolues par `os.environ.get`) doivent
  être de **vraies variables d'env**, pas dans le `.env`. Précédence : `env réel > .env > YAML > défauts`.
- Ligne max **100** caractères (ruff). Enums = `StrEnum` (pas `(str, Enum)`).
