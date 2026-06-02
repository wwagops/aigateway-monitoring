# Contribuer

## Convention de messages de commit — Gitmoji

Les commits suivent la convention **[Gitmoji](https://gitmoji.dev)** : un emoji en tête de
message exprime l'**intention** du changement. C'est lisible d'un coup d'œil et ça rend
l'historique filtrable.

### Format

```
<gitmoji> [(scope)] <sujet à l'impératif>

[corps optionnel : le « pourquoi », pas le « comment »]

[pied optionnel : BREAKING CHANGE: …, Refs #123, Co-Authored-By: …]
```

- **gitmoji** : l'emoji Unicode (`✨`) **ou** son raccourci (`:sparkles:`) — les deux sont
  acceptés (voir la liste complète sur <https://gitmoji.dev>).
- **scope** (optionnel) : le module concerné, entre parenthèses. Scopes du projet :
  `config`, `probes`, `checks`, `runner`, `db`, `api`, `metrics`, `cli`, `scheduler`,
  `docker`, `ci`, `deps`, `docs`.
- **sujet** : à l'**impératif présent**, sans point final, ≤ 72 caractères. **Un seul**
  changement logique par commit.

### Emojis les plus utilisés ici

| Emoji | Code | Quand l'utiliser |
|---|---|---|
| 🎉 | `:tada:` | amorce d'un projet (commit initial) |
| ✨ | `:sparkles:` | nouvelle fonctionnalité |
| 🐛 | `:bug:` | correction de bug |
| 🩹 | `:adhesive_bandage:` | petit correctif non critique |
| 🚑️ | `:ambulance:` | hotfix critique |
| ♻️ | `:recycle:` | refactorisation (sans changer le comportement) |
| 🏗️ | `:building_construction:` | changement d'architecture |
| 🎨 | `:art:` | structure / format / lisibilité du code |
| ⚡️ | `:zap:` | performance |
| 🔥 | `:fire:` | suppression de code ou de fichiers |
| ⚰️ | `:coffin:` | suppression de code mort |
| 🗃️ | `:card_file_box:` | changements liés à la base de données / migrations |
| 🦺 | `:safety_vest:` | validation (config, entrées) |
| 🛂 | `:passport_control:` | auth / clés / permissions |
| 🔒️ | `:lock:` | sécurité ou confidentialité |
| 🧵 | `:thread:` | concurrence / asynchrone |
| 🩺 | `:stethoscope:` | healthcheck / sondes |
| 🔊 | `:loud_sound:` | ajout ou mise à jour de logs |
| ✅ | `:white_check_mark:` | ajout / mise à jour de tests |
| 🧪 | `:test_tube:` | ajout d'un test qui échoue (TDD) |
| 📝 | `:memo:` | documentation |
| 📄 | `:page_facing_up:` | licence (ajout / mise à jour) |
| 💡 | `:bulb:` | commentaires dans le code |
| 🏷️ | `:label:` | types / annotations |
| 🚨 | `:rotating_light:` | corrige des avertissements (ruff / mypy) |
| 👷 | `:construction_worker:` | CI (système de build) |
| 💚 | `:green_heart:` | répare une CI cassée |
| ⬆️ | `:arrow_up:` | montée de version de dépendances |
| ⬇️ | `:arrow_down:` | rétrogradation de dépendances |
| 📌 | `:pushpin:` | épingler des dépendances |
| 🧱 | `:bricks:` | infrastructure (Docker, compose) |
| 🚚 | `:truck:` | déplacement / renommage de fichiers |
| 🙈 | `:see_no_evil:` | `.gitignore` |
| 💥 | `:boom:` | changement cassant (breaking change) |
| 🔖 | `:bookmark:` | tag de version / release |
| ⏪️ | `:rewind:` | annulation (revert) de changements |
| ✏️ | `:pencil2:` | correction de fautes de frappe |
| 🧑‍💻 | `:technologist:` | expérience développeur (DX) |

> Liste exhaustive et recherche : <https://gitmoji.dev>. La CLI [`gitmoji-cli`](https://github.com/carloscuesta/gitmoji-cli)
> (`gitmoji -c`) aide à composer les messages.

### Exemples (intentions réelles du projet)

```
✨ (config): ajoute model_defaults (capacités par nom de modèle, cross-org)
✨ (db): bascule sur SQLite local si aucune URL n'est fournie
🐛 (api): sert /metrics en 200 sans redirection 307
♻️ (checks): rend les capacités pluggables via un registre
🏗️ (db): stocke les capacités dans une colonne JSONB générique
🗃️ (db): migration 0002 — capabilities JSONB, drop des colonnes par capacité
🎨 (cli): tableau aligné et coloré, logs basculés sur stderr
🦺 (config): précédence des capacités defaults < org < model_defaults < (org,modèle)
🔒️ (api): masque base_url par défaut, ne journalise jamais les clés
✅ (config): teste la précédence et le deep-merge des capacités
📝 (docs): documente l'ajout d'une capacité et le fallback SQLite
👷 (ci): GitHub Actions + GitLab CI (ruff, mypy, pytest, migrations)
🧱 (docker): image multi-stage et docker-compose (postgres + migrate + monitor)
```

### Règles

- **Un emoji** par commit : celui de l'intention principale.
- Sujet à l'**impératif** (« ajoute », « corrige »), minuscule, sans point final, ≤ 72 car.
- Commits **atomiques** : un changement cohérent et testable à la fois.
- Avant de committer : `ruff check . && mypy src && pytest` doivent passer
  (voir [`CLAUDE.md`](CLAUDE.md)).
- **Changement cassant** : `💥` en tête du sujet **et/ou** `BREAKING CHANGE: …` dans le pied.
- Référencer un ticket dans le pied : `Refs #42`, `Closes #42`.
- Les commits assistés par IA conservent le trailer `Co-Authored-By: …`.

## Mise en place de l'environnement

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Voir le [README](README.md) pour l'utilisation et [`CLAUDE.md`](CLAUDE.md) pour la carte de
l'architecture et les invariants à respecter.
