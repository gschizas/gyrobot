# Installation

## How dependencies work

Dependencies come in two layers:

1. **Core**: listed in `pyproject.toml`, installed by `uv sync`. Needed by every instance.
2. **Plugin**: each plugin (chat platform or command module) declares the libraries only it
   needs in its own `PLUGIN = {'dependencies': [...]}` (e.g. `kubernetes` for the OpenShift
   commands, `discord.py` for Discord).

Which plugins are active depends on the **environment variables** of the instance
(`.env.d/<name>.env`) and on `config/plugins.yml`. So the plugin libraries to install differ
per instance, and `uv sync` alone is **not enough**: it installs only the core and also
*removes* any plugin library already installed.

## Installing on a server

```sh
git clone <repo-url> bot && cd bot
git submodule update --init                 # bot_framework

# 1. Instance configuration (not in git)
mkdir -p .env.d config data logs .refreshtoken
$EDITOR .env.d/myinstance.env               # tokens, SUBREDDIT_NAME, GITHUB_TOKEN, WEBAPP_PORT, ...
$EDITOR config/plugins.yml                  # optional, see below

# 2. Core dependencies
uv sync

# 3. Libraries of the plugins this instance enables
uv run python src/plugins.py requirements myinstance | uv pip install -r -

# 4. Run in the foreground to check (from the repository root)
uv run python src/__main__.py myinstance        # the bot
uv run python src/run_webapp.py myinstance      # the web UI + REST API
```

- `requirements myinstance` reads `.env.d/myinstance.env` exactly as the bot does and prints the
  pip requirements of every plugin that would load. Without a name it uses the process
  environment (useful when variables are injected by Docker).
- Rerun step 3 after every `uv sync`, and whenever you change the env file, `config/plugins.yml`
  or pull a new version. (`uv sync --inexact` keeps already-installed extras.)
- A plugin whose library is missing is skipped and logged, e.g.
  `command plugin generic.financial: missing packages: yfinance>=0.2.43`. If it is the selected
  chat platform, startup fails with the same message.
- Always run from the repository root; the bot reads `config/` and `data/` relative to it.

## Running as systemd services

`deploy/systemd/` contains two **template units**, so one file serves every instance
(the text after `@` is the env name, i.e. `.env.d/<name>.env`):

| Unit | Runs |
|---|---|
| `gyrobot@<name>.service` | `src/__main__.py <name>` (the chat bot) |
| `gyrobot-web@<name>.service` | `src/run_webapp.py <name>` (web UI + REST API) |

Both units run `plugins.py requirements <name> | uv pip install` before starting, so the plugin
libraries are installed automatically on every (re)start; you only need `uv sync` after an update.

```sh
uv sync                                          # core dependencies
sudo deploy/install_services.sh                  # renders the units for $SUDO_USER and this directory
sudo systemctl enable --now gyrobot@myinstance
sudo systemctl enable --now gyrobot-web@myinstance   # only if you want the web UI/API
```

Operations:

```sh
systemctl status gyrobot@myinstance
journalctl -u gyrobot@myinstance -f
sudo systemctl restart gyrobot@myinstance        # after changing config/ or .env.d/
```

After `git pull`: `uv sync`, then run the database migrations (see below), then
`sudo systemctl restart gyrobot@myinstance gyrobot-web@myinstance`.

### Database migrations

The schema is managed by Alembic. Run it after every pull that adds a file under
`migrations/versions/`, **before** restarting (the new code expects the new tables):

```sh
deploy/migrate.sh
```

`deploy/migrate.sh` (needs `whiptail`) lists the instances in `.env.d/`, then asks for the database
user (default `postgres`) and its password. It reuses the host, port and database from the
instance's env file, runs `alembic upgrade head` and `alembic check`, and forgets the password when
it exits. On Windows use `deploy\windows\migrate.ps1`, which does the same with text prompts (no `whiptail`).

To do it by hand: the password does not have to be in the URL (and so needs no escaping), because
libpq reads `PGPASSWORD`:

```sh
export PGPASSWORD='<password>'
export MIGRATIONS_DATABASE_URL='postgresql://<owner>@<host>/<database>'
uv run alembic -x env=myinstance upgrade head
uv run alembic -x env=myinstance check        # optional: model vs. database drift
unset PGPASSWORD MIGRATIONS_DATABASE_URL
```

`MIGRATIONS_DATABASE_URL` takes precedence over the `*_DATABASE_URL` variables in the env file. Use
it with a role that **owns** the tables, because the bot's normal database
user usually does not (`CREATE INDEX IF NOT EXISTS` and `ALTER TABLE` need ownership even when
nothing changes). Set it only for this command; do not put it in `.env.d/`. If the normal user
owns the tables, you can skip the variables.

The units are rendered with the user, repository directory and `uv` path filled in; rerun
`install_services.sh` if you move the checkout or change the user. The web app binds to
`WEBAPP_HOST`/`WEBAPP_PORT` from the env file; put a TLS-terminating reverse proxy in front of it.

Migrating from the old hand-made `slack-bot-<name>.service` units: stop and disable them
(`systemctl disable --now slack-bot-<name>`), delete the files and the `.service.d` directories
from `/etc/systemd/system`, then enable the new units.

## Running as Windows services (WinSW)

The Windows equivalent of the `systemd` units uses [WinSW](https://github.com/winsw/winsw), which
wraps a command as a real Windows service (auto-restart, rolling log files). `deploy/windows/`
contains one XML template (`service.xml`) and an installer. Prerequisites: `uv` on the `PATH`, and
steps 1–3 of "Installing on a server" done in the checkout.

From an **elevated** PowerShell in the repository root:

```powershell
deploy\windows\install_services.ps1 -Instance myinstance            # the bot
deploy\windows\install_services.ps1 -Instance myinstance -Web       # the bot and the web UI/API
```

This creates the services `gyrobot-myinstance` and `gyrobot-web-myinstance`, using the same names
as the Linux units. It downloads WinSW (v3, needed for the pre-start hook) into `.winsw\` on first
use, generates `.winsw\<service>.exe` and `.xml` (git-ignored), installs them and starts them.

- Like the Linux units, each service installs the instance's plugin libraries before starting.
- `-Credential (Get-Credential)` runs the services as a specific account. The default,
  LocalSystem, usually cannot see a per-user `uv` installation, so use the account that owns the
  checkout.
- Logs: WinSW's own `.out.log`/`.err.log`/`.wrapper.log` go to `logs\`, next to the bot's logs.
  `PYTHONUTF8=1` is set so emoji don't break the console encoding.
- Manage them with the normal tools: `Get-Service gyrobot-*`, `Restart-Service gyrobot-myinstance`,
  or `.winsw\gyrobot-myinstance.exe status|restart|stop`.
- After `git pull`: run `uv sync`, then the database migrations (set `$env:PGPASSWORD` and
  `$env:MIGRATIONS_DATABASE_URL` for the owner, run `uv run alembic -x env=myinstance upgrade head`, then
  remove both variables; see "Database migrations" above), then
  `Restart-Service gyrobot-myinstance` (and the web one).
- `-RenderOnly` only generates the files, for review; `-Uninstall` removes the services.
- To make the services depend on something (e.g. a local database), add `<depend>` entries to
  `deploy\windows\service.xml` and rerun the installer.

## `config/plugins.yml` (optional)

```yaml
chat: auto          # auto = first platform whose env vars are set (by priority), or slack/discord/teams/telegram/mattermost
commands:
  enable: [generic, roll]   # optional whitelist; a name also covers its submodules (reddit -> reddit.nuke)
  disable: [weather]        # always off
```

Disabled plugins are not imported and their libraries are not listed by `requirements`.

## Adding a plugin's libraries

Put them in the plugin's own `PLUGIN` dict, not in `pyproject.toml`:

```python
PLUGIN = {'requires': ['MY_API_TOKEN'], 'dependencies': ['somelib>=1.2']}
```

Only libraries shared by several plugins or by the core belong in `pyproject.toml`.

## Docker

The current `Dockerfile` is out of date (it references a missing `requirements.txt` and
`slack_bot.py`). When updating it, run `uv sync --frozen` at build time and install the plugin
libraries at start-up, when the instance's environment is available:

```sh
uv run python src/plugins.py requirements | uv pip install -r - && uv run python src/__main__.py <name>
```
