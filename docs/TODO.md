# TODO

## Notifications for the Web UI / REST API

`backend.notifications.notify()` currently only reaches the chat platform
(Slack/Mattermost), through the sender registered in `__main__.py`
(`chat.get_notification_sender`). Background events such as GitHub invitation
accepted/expired are not visible in the web UI or API. Options:

- Persist notifications in a table (e.g. `notifications`: id, created_at, text, read)
  from `notify()`, and show them on the web dashboard (and a `GET /api/notifications` endpoint).
- Support multiple senders in `backend.notifications` (chat, webhook, email via
  `backend.email_logging`) instead of a single one.
- Add a webhook callback URL per OAuth2 client in `config/oauth2_clients.yml` so API
  consumers get pushed events.
- Note: the web app can run in a separate process from the bot, so an in-memory
  sender isn't enough; the database is the shared channel.

## Review suggestions

1. **Repeated notifications on assignment failure**: if `add_users_to_ent_team` fails, the
   provision stays `invited` and every background cycle retries and re-notifies. Record
   `failed_at`/`last_error` in the provision data (or use a `failed` status) and only notify on change.
2. **Case-sensitive login matching** in `check_github_invitations` (`username in all_user_logins`):
   compare lowercased on both sides (older provisions may have the wrong casing).
3. **Approvals-channel notification on failure**: the exception path in `_approve_one`
   (`commands/approvals.py`) should also notify the approvals channel.
4. **Inconsistent validation errors** in `_github_validate`: user-not-found returns a message, but
   bad team / email domain raise `RuntimeError`. Return strings for all.
5. **No tests**: add pytest coverage for `_parse_id_spec`, `convert_slack_emoji`,
   `flatten_team_tree` and the invitation expiry decision.
6. **Single notification sender**: `backend.notifications.set_sender` supports only one sender
   and the web process has none (see the notifications section above).

## Planned features and design notes

1. **Crowd onboarding in gyrobot** (chat bot and web UI): incorporate the existing Crowd onboarding code.
   **Do not write any Crowd onboarding code until the existing scripts have been pasted.** They mostly validate
   that the account exists in AD/LDAP before adding it, and then assign the proper team. `onboard crowd` and
   `backend/providers/crowd.py` are currently stubs.
2. **Secrets storage**: a pluggable secret store now exists (`backend/secret_store`, see `SECRET-STORE.md`) with
   systemd, directory, `pass`, keyring and Azure Key Vault backends; remaining work is choosing a backend, moving the
   real secrets, and routing the `config/*.credentials.yml` files through it.
   (Options and trade-offs are in `SECRETS-OPTIONS.md`; systemd credentials need systemd 250+,
   so they're parked until the server leaves Ubuntu 22.04; see `SYSTEMD-CREDENTIALS.md`.) Plain-text files holding passwords/tokens are not good enough. The server runs on Linux, so
   there is no DPAPI equivalent. Evaluate alternatives (e.g. systemd credentials, an OS keyring or secret service,
   Vault or another secrets manager, or encrypting at rest with a key kept outside the config directory).
3. **`accounts.name` column**: it is not used properly (currently the GitHub username is written there), and it may
   not be needed at all. The GitHub username (login) should not live there; if anything it should be a calculated
   column derived from the account's GitHub provision (`data->>'username'`, or looked up by the stored `github_id`
   so that it survives renames). Decide whether to drop `name` or give it a proper meaning (the person's real name).
4. **Backfill `invitation_id`** (and `github_id`) in existing GitHub provisions: rows created before the
   `github_cancel` command lack it; `github_cancel` copes by matching on login/email, but the id could be filled in
   from the pending invitations for `invited` rows.
5. **`ProvisionRequest` cleanup** (`backend/providers/base.py`, formerly `Account`):
   - `userid` and `team` are required, but `onboard slack`, `onboard crowd`, `onboard jetbrains` and `offboard`
     build it with only `name` and `email`, which raises `TypeError`. Give both a default of `''`.
   - Rename the `provision_data` field to `result_data`, and the `account` parameter of the provider functions to
     `request`.
   - Tidy the old `Account as ProviderAccount` import aliases.
6. **Permissions web page**: a page to manage permissions. Gather all functions that need permissions
   (reflection over the registered commands / `check_security` and `requires_approval` decorators?). Open question:
   how to handle roles. It should present a list of people to choose from, either from Slack or from the
   active directory.
7. **Store active directory users with their domain**: store e.g. `jdoe@example.com` instead of just `jdoe`.
8. **Move all database access to SQLAlchemy + Alembic**. Everything the bot owns is one PostgreSQL database, so use
   a single migration history, and move the queries from psycopg to SQLAlchemy as well (not only the schema).
   Do it one functional group at a time, least complicated first, each as its own commit:
   1. **DONE (pending a test on the real database)** kudos (`kudos` table, `commands/kudos.py`) - this one also sets up Alembic (`alembic` and `sqlalchemy`
      dependencies, a `postgresql+psycopg://` URL, `env.py` using `backend.secret_store.load_environment`) and the
      baseline `0001`; the kudos table definition comes from `pg_dump --schema-only -t kudos`.
   2. **DONE (pending a test on the real database)** permissions (`permission_rules`, `backend/permissions.py`, DDL now in `scripts/migrate_permissions.py`).
   3. **DONE (pending a test on the real database)** onboarding / offboarding / approvals (`accounts`,
      `account_provisions`, `account_provision_history`, `account_history`, `approval_requests`); migration `0003`
      adds `accounts.team` and `account_history` where they are missing.
   - For each group: define the SQLAlchemy models, write the migration (idempotent, so it is safe on existing
     databases), switch the queries over, and delete the old `_SCHEMA` strings and table creation.
   - Remaining: run `alembic upgrade head` and `alembic check` on the real database (PostgreSQL 9.5 is below what
     SQLAlchemy officially supports). Migrations that really change a table need a role that owns it, so run them
     with `MIGRATIONS_DATABASE_URL` set to the owner's connection string (`CREATE INDEX IF NOT EXISTS` and
     `ALTER TABLE` demand ownership even when nothing changes). Document `alembic upgrade head` as a deploy step
     (maybe in the Docker
     entrypoint). Decide whether the bot, web UI and API refuse to start, or only warn, when the database is behind.
     `scripts/check_schema.py` was removed in favour of `alembic check`.
9. **Leftovers from the removed `cheese`, `too_many_posts` and `survey` commands** (code and docs are already removed):
   - Remove `CHEESE_DATABASE_URL`, `GYROBOT_DATABASE_URL`, `QUESTIONNAIRE_DATABASE_URL` and `QUESTIONNAIRE_FILE` from
     the `.env.d` files, the questionnaire YAML from `data/` and `data/cheese_agent.yml` on the server, and any
     permission rules (`permission_rules`) naming the three commands.
   - Optionally drop the `"machineState"`, `"jobQueue"`, `"Votes"`, `"Answers"` and `"Receipts"` tables and
     `public.submissions`; they stay out of the Alembic baseline.

## Per-instance configuration and data

Several instances run from one checkout (`.env.d/<name>.env`), but `config/` and `data/` are shared between them,
and `data/` files are told apart with `-<LOG_NAME>` suffixes. Decided, not started:

- An **instance** is the same thing as an environment name (`.env.d/<name>.env`, the argument of `__main__`).
- **Overlay lookup** for configuration: `config/<instance>/<file>` first, then `config/<file>`. Nothing is meant to
  be shared in practice, but the fallback keeps existing single-instance setups working without a migration.
- **`data/` becomes per instance too**: `data/<instance>/<file>`, and the `-<LOG_NAME>` suffixes go away
  (`state_file`, `teams_conversations-<LOG_NAME>.yml`, ...). The cronjob stack, `crowd_users.yml` and the
  `SHORTCUT_WORDS` files move there as well. None of the files once considered "likely shared"
  (`team_mapping.yml`, `kubernetes_servers.yml`, `crowd_users.yml`, the covid data) should be shared.

Scope:

- One helper (e.g. `config_path(name)` / `data_path(name)`) replacing the hard-coded paths in `plugins.py`
  (`plugins.yml` and the `requires_files` check), `backend/github_api.py`, `backend/email_domains.py`,
  `backend/email_logging.py`, `backend/team_mapping.py`, `backend/configuration.py` (`read_config`,
  `kubernetes_servers.yml`, `crowd_users.yml`), `backend/secret_store`, `webapp/config.py`,
  `commands/reddit/__init__.py` (`enhanced_crowd_control.yml`, which is also written at runtime),
  `commands/openshift/*` (cert files, cronjob stack, `docker_deploy.py`), `__main__.py` (`SHORTCUT_WORDS`),
  `state_file.py`, `commands/generic/covid19.py` and `chat/teams.py`.
- The scripts that read `config/` (`migrate_permissions.py`, `backfill_jetbrains.py`, `import_provisions.py`)
  need the same helper plus an instance argument.
- `run.sh`, `run.ps1`, the `Dockerfile` and `INSTALLATION.md` (which says everything is read from the repo root).
- Existing inconsistency: `docker_deploy.py` reads `<config>.credentials.yaml`, everything else `.yml`.
- `config/ldap.yml` and `config/users.ldif` are not read by any code (LDAP uses env vars); decide whether to delete.

Open questions:

1. **How does the code know the instance?** Export an env var (e.g. `INSTANCE`) in `__main__` and
   `load_environment` (`LOG_NAME` is being removed, see the logs section). The web UI and REST API processes must
   set it too.
2. **Run without an instance name?** Fall back to plain `config/` and `data/`, or make the name mandatory?
3. **Existing `data/` files**: migrate them (rename `*-<LOG_NAME>.yml` into `data/<instance>/`) with a one-off
   script, or leave a fallback read of the old name?
4. **Files written at runtime** (`enhanced_crowd_control.yml`, the cronjob stack): move the first from `config/` to
   `data/<instance>/`, or keep it in `config/<instance>/`?
5. **Paths given in env vars** (`*_CONFIGURATION`): resolve relative ones through the overlay, and keep absolute
   paths working?
6. **Plugin gating**: should `requires_files` resolve through the same overlay? `python src/plugins.py requirements
   <env-name>` already knows the instance.
7. **Credentials and permissions siblings** (`<name>.credentials.yml`, `<name>.permissions.yml`): resolve each
   through the overlay independently, or together with the main file?
8. **Containers**: mount one `config/<instance>` and `data/<instance>` per container, or the whole folders?

## Per-instance logs

Decided, not started:

- Layout: `logs/<instance>/gyrobot.log` (INFO) and `logs/<instance>/gyrobot.debug.log` (DEBUG). The instance name
  appears only in the folder, never in the file name. The weekly rotation (`LOG_ROLLOVER`, default `W0`) and the
  separate debug file stay as they are.
- The **web UI and REST API get their own log files** in the same folder, named after the app only
  (e.g. `gyrobot-web.log`, `gyrobot-api.log`, plus their `.debug.log`). They never call `setup_logging` today.
- **`LOG_NAME` is removed** (also from the `.env.d` files and the docs); the instance variable from the per-instance
  work replaces it. `state_file` and `chat/teams.py` stop using it too.
- **Old logs are zipped by hand** and the new scheme starts clean; no migration code.
- **Debug log can be disabled** with an environment variable (name to be decided, e.g. `LOG_DEBUG=false`); the
  default stays on.
- Current naming (`setup_logging` in `src/bot_framework/common.py`) depends on how the process is started:
  - `python src/__main__.py <env>`: `sys.argv[0]` is `__main__.py`, so it uses the checkout folder name (one level
    above `src`), giving `<folder>-<instance>.log`. That is the Windows case.
  - `python src` (a directory, presumably how it is started on Linux): `sys.argv[0]` is `src`, the `__main__`
    branch is skipped, and the result is `src-<instance>.log`.
- `setup_logging` is only called from `__main__.py`; `LOG_NAME` is passed to it as the suffix.

Scope:

- `setup_logging` takes an app name (`gyrobot`, `gyrobot-web`, `gyrobot-api`) and a log folder instead of deriving
  the name from `sys.argv[0]` and the folder name; each entry point passes both, and the web UI and API call it.
- The WinSW wrapper logs (`.out.log`, `.err.log`, `.wrapper.log`, see `INSTALLATION.md`) also go to `logs\`;
  decide where they end up in the new structure.
- Update `INSTALLATION.md`, `.github/copilot-instructions.md` (the logging, `LOG_NAME` and `state_file` rows), and
  the logrotate or systemd/journal notes, if any.

Open questions:

1. **Name of the variable that disables the debug log**, and whether it should also allow a level
   (e.g. `LOG_LEVEL`) instead of only on/off.
2. **Where the logging code lives**: depends on the `bot_framework` decision below.

## Dropping the `bot_framework` submodule

Reddit is retiring the Data API and the remaining scripts are being migrated, so the submodule
(`src/bot_framework`, `../bot_framework.git`) may no longer be needed. Not decided. What this repo still takes
from it:

| Used | Where | If the submodule goes |
|---|---|---|
| `yaml_wrapper.yaml` | 11 modules (`state_file`, `plugins`, `backend/*`, `webapp/config`, `secret_store`, `reddit`) | move the shared YAML instance into this repo (e.g. `src/yaml_wrapper.py`) and change the imports |
| `common.setup_logging` | `__main__.py` | rewrite here as part of the per-instance logs work |
| `common.normalize_text` | `__main__.py` (trigger-word matching) | move here; it downloads the Unicode confusables table on first use, so decide whether to vendor the file |
| `praw_wrapper.praw_wrapper` | `__main__.py` (Reddit OAuth) | goes away with the Reddit commands |
| `slack.SlackWrapper` | only used by `common.send_to_slack` | not needed |

Open questions:

1. **Does the Reddit support go away completely** (the `commands/reddit/` package, `praw`, the `.refreshtoken/`
   folder, `REDDIT_*` variables, the `ctx.subreddit` / `ctx.reddit_session` properties, the Reddit rows in the docs),
   or only the parts that need the Data API?
2. **Do the other projects still use `bot_framework`?** If so, only the submodule reference is removed from here;
   the code is copied, not deleted.
3. **Order**: dropping the submodule is simplest after the Reddit decision, and before the logging rewrite, so
   `setup_logging` is written once in its final place.
4. **History**: remove the submodule cleanly (`git submodule deinit`, remove `.gitmodules` and the path), and update
   `INSTALLATION.md` (`git submodule update --init`) and the Docker build.

## Install under `/opt/<company>/`

Wanted, not started: make the bot installable like another internal app, which has a `deploy/` folder with an
Ubuntu install guide (`INSTALL-ubuntu.md`), a systemd unit and an Apache snippet
(`O:\GSchizas\Documents\Source\Python\Eurobank\BookingParking\deploy`). What that app does, as a starting point:

- App in `/opt/<company>/<app>`, a system user with `/opt/<company>` as its home, and `uv sync --frozen --no-dev`
  with `UV_PYTHON_INSTALL_DIR=/opt/<company>/python` so the service does not depend on `/home`.
- Settings in `/etc/<app>.env` (mode 600), read through the systemd `EnvironmentFile`.
- A hardened systemd unit (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`) with
  `Restart=on-failure` and `alembic upgrade head` as `ExecStartPre`.
- Apache as the TLS reverse proxy in front of uvicorn on `127.0.0.1`.
- An "Updating" section (`git pull`, `uv sync`, restart).

Open questions:

1. **Company name** to use in the path.
2. **Several instances**: a systemd template unit (`gyrobot@<instance>`, which `INSTALLATION.md` already mentions)
   with `/etc/<app>/<instance>.env`, and separate units for the bot, the web UI and the REST API?
3. **Writable locations**: with `ProtectSystem=strict`, `config/`, `data/`, `logs/` and `.refreshtoken/` need
   `ReadWritePaths=`, or must move to `/etc`, `/var/lib` and `/var/log`. Which layout?
4. **Instance files** (`config/<instance>/`, `data/<instance>/`): inside the checkout or outside it (e.g.
   `/etc/<app>/<instance>/`, `/var/lib/<app>/<instance>/`)? Depends on the per-instance work above, so do that
   first.
5. **Web UI and API**: reverse proxy through Apache with a root path (like the other app), or one port per
   instance?
6. **Plugin libraries**: `INSTALLATION.md` installs them per instance with `src/plugins.py requirements <env-name>`.
   With one shared virtualenv in `/opt`, how are the instances' libraries installed together, and by whom?
7. **Existing deployment files**: replace the stale `Dockerfile` and `run.*` scripts, or keep both styles?

## Other chat platforms

Mattermost, Discord, Telegram and Teams gaps are tracked in `TODO-chat-platforms.md`.
