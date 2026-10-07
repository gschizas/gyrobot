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

After `git pull`: `uv sync && sudo systemctl restart gyrobot@myinstance gyrobot-web@myinstance`.

The units are rendered with the user, repository directory and `uv` path filled in; rerun
`install_services.sh` if you move the checkout or change the user. The web app binds to
`WEBAPP_HOST`/`WEBAPP_PORT` from the env file; put a TLS-terminating reverse proxy in front of it.

Migrating from the old hand-made `slack-bot-<name>.service` units: stop and disable them
(`systemctl disable --now slack-bot-<name>`), delete the files and the `.service.d` directories
from `/etc/systemd/system`, then enable the new units.

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
