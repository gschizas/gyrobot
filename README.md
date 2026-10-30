# GyroBot

A chat bot (Slack, Mattermost, Discord, Telegram, Teams) that moderates a subreddit, manages OpenShift/Kubernetes
workloads, onboards and offboards colleagues through an approval queue, and offers a few utility commands. The same
onboarding functions are also available through a web UI and a REST API.

Commands are [Click](https://click.palletsprojects.com/) commands. Type the bot's trigger word (`bot` in the examples)
followed by the command.

## Using the bot

```
bot <command> [subcommand] [arguments] [options]
bot help <command>            # same as: bot <command> --help
```

- The first word of `BOT_NAME` is the primary trigger word. Look-alike Unicode characters are normalised, so they
  cannot be used to get around it.
- Output printed by a command is sent back as a code block.
- Commands are only loaded when the environment they need is present (for example the Reddit commands need
  `SUBREDDIT_NAME`). `bot help` lists what is available in your instance.
- Many commands check permissions (user and channel) before running. See [Permissions](docs/PERMISSIONS.md).
- Table-producing commands accept `-f/--format` (`table`, `markdown`, `excel`, `zip_markdown`) or `-x/--excel`.
  The `github` listing commands also add `team L2` and `team L3` formula columns to Excel output.

## Command reference

| Area | Commands | Document |
|---|---|---|
| Reddit moderation | `modqueue`, `usernotes`, `nuke`, `archive`, `history`, `comment_source`, `deleted_comment_source`, `configure_enhanced_crowd_control`, `add_domain_tag`, `add_policy`, `youtube_post_info`, `unicode_post`, `make` | [docs/REDDIT.md](docs/REDDIT.md) |
| OpenShift / Kubernetes | `deployment`, `cronjob`, `scaledown`, `actuator`, `mock`, `deploy` | [docs/OPENSHIFT.md](docs/OPENSHIFT.md) |
| Onboarding | `onboard github/jetbrains/crowd/slack/move`, `offboard`, `github`, `jetbrains` | [docs/ONBOARDING.md](docs/ONBOARDING.md) |
| Approval queue | `approvals list/show/approve/reject` | [docs/APPROVALS.md](docs/APPROVALS.md) |
| Permissions | `permissions reload/show` | [docs/PERMISSIONS.md](docs/PERMISSIONS.md) |
| Web UI and REST API | onboarding forms, permission rule management, `/api/...` endpoints | [docs/WEB-AND-API.md](docs/WEB-AND-API.md) |
| Everyday utilities | `weather`, `convert`, `roll`, `cointoss`, `kudos`, `stocks`, `crypto`, `covid`, `joke`, `fortune`, `ud`, `binary`, `unicode`, `uptime`, `disk_space`, `version` ... | [docs/UTILITIES.md](docs/UTILITIES.md) |

## Setup and operations

| Document | Contents |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Installing, plugins, systemd/Windows services, Docker |
| [docs/SECRET-STORE.md](docs/SECRET-STORE.md), [docs/SECRETS-OPTIONS.md](docs/SECRETS-OPTIONS.md), [docs/AZURE-KEY-VAULT.md](docs/AZURE-KEY-VAULT.md), [docs/SYSTEMD-CREDENTIALS.md](docs/SYSTEMD-CREDENTIALS.md) | Keeping secrets out of the environment files |

Quick start (from the repository root; the bot must always run from there):

```sh
git submodule update --init
uv sync
uv run alembic -x env=<env-name> upgrade head     # database schema
python src/__main__.py <env-name>                 # loads .env.d/<env-name>.env
```

## Which commands are enabled

Each command module declares what it needs in a `PLUGIN` dictionary (environment variables and libraries).
A module is loaded only if its requirements are met. `config/plugins.yml` can pick the chat platform and enable or
disable commands by name. Details are in [docs/INSTALLATION.md](docs/INSTALLATION.md).

| Command group | Needs |
|---|---|
| Reddit commands | `SUBREDDIT_NAME` (`make` also needs `REDDIT_ALT_USER`) |
| `deployment`, `cronjob`, `scaledown`, `actuator`, `mock`, `deploy` | `OPENSHIFT_DEPLOYMENT`, `OPENSHIFT_CRONJOB`, `OPENSHIFT_SCALEDOWN`, `OPENSHIFT_ACTUATOR_REFRESH`, `MOCK_CONFIGURATION`, `DOCKER_DEPLOY_CONFIGURATION` |
| `onboard`, `offboard`, `approvals` | `APPROVAL_DATABASE_URL` |
| `github` | `config/github.yml` |
| `jetbrains` | `JETBRAINS_TOKEN`, `JETBRAINS_CUSTOMER_CODE` |
| `kudos` | `KUDOS_DATABASE_URL` |
| `weather` | `WEGO_EXE` or `WEATHER_URL` |
| `permissions` | none (needs the permissions database to be useful) |
| Utilities | none |
