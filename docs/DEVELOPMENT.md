# Development quickstart

How to run the web UI and the chat bot on your own machine. Run every command from the **repository root**.
For a server install see [INSTALLATION.md](INSTALLATION.md).

## 1. Prerequisites

- Python 3.14 and [uv](https://docs.astral.sh/uv/). On a machine with a newer Python, pin it
  (`uv sync --python 3.14`), because some dependencies have no wheels for the newest release yet.
- PostgreSQL for the onboarding data and the permission rules (any reachable instance; a throwaway one in Docker
  is fine).
- [Mokapi](https://mokapi.io/docs/get-started/installation) to stand in for the LDAP directory (see step 4).
- `config/github.yml` (and the other `config/` files of the features you use). The onboarding commands are not
  loaded without it.

## 2. Install

```powershell
git submodule update --init
uv sync --python 3.14
uv run python src/plugins.py requirements dev | uv pip install -r -
```

Run the last line again after every `uv sync`: `uv sync` removes the plugin libraries.

## 3. The instance file

`.env.d/dev.env` is not in git. A minimum for the web UI:

```ini
# Web UI
WEBAPP_SESSION_SECRET=any-long-random-string
WEBAPP_JWT_SECRET=another-long-random-string
WEBAPP_ROOT_PATH=/
WEBAPP_ALLOWED_HOSTS=localhost,127.0.0.1
WEBAPP_PORT=5709

# Login against the Mokapi LDAP server (step 4)
LDAP_SERVER=ldap://127.0.0.1:1389
LDAP_USERNAME_PATTERN=uid={},dc=example,dc=com
LDAP_AUTHENTICATION_TYPE=SIMPLE

# Database
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/gyrobot
```

Notes:

- `WEBAPP_ROOT_PATH` defaults to `/eurobot/`, the prefix used behind the reverse proxy. For development `/` is
  simpler, so the site is at `http://localhost:5709/`. With the default, use `http://localhost:5709/eurobot/`.
- `WEBAPP_ALLOWED_HOSTS` lists the host names the site answers to (anything else gets a 400).
- `LDAP_AUTHENTICATION_TYPE` defaults to `NTLM`, which a mock directory cannot do. Use `SIMPLE` there. In
  production leave it out (or set it as your directory needs).
- The chat variables (`SLACK_*`, `BOT_NAME`, ...) are optional for the web UI. Without them it logs
  "Chat notifications disabled" and carries on, but approval announcements are not posted anywhere.

## 4. A fake LDAP directory with Mokapi

The web UI logs a user in by binding to LDAP as that user (`LDAP_USERNAME_PATTERN` with the typed name put in
place of `{}`). Mokapi can serve such a directory from a file, so no real directory is needed.

`dev/ldap/` holds a ready configuration (`ldap.yml` and `users.ldif`) with two users, `alice` and `bob`. Start
Mokapi in its own terminal and leave it running:

```powershell
mokapi dev\ldap\ldap.yml
```

It listens on `127.0.0.1:1389`. Mokapi watches the files, so edits to `users.ldif` apply without a restart.

- To log in, type `alice` and `alice-dev-password` (see the file). Mokapi compares the password with the
  `userPassword` of the entry as plain text, and an entry without `userPassword` accepts any password.
- Add a user by adding an entry, for example:

  ```ldif
  dn: uid=carol,dc=example,dc=com
  cn: Carol Example
  uid: carol
  userPassword: carol-dev-password
  ```

- The user part of the DN must match the `LDAP_USERNAME_PATTERN`: with `uid={},dc=example,dc=com`, logging in as
  `alice` binds as `uid=alice,dc=example,dc=com`. If you already keep your own Mokapi files (for example in
  `config/`), use them and set the pattern to match their DNs.
- Check the directory without the web UI:

  ```powershell
  uv run python -c "import ldap3; c = ldap3.Connection(ldap3.Server('ldap://127.0.0.1:1389'), user='uid=alice,dc=example,dc=com', password='alice-dev-password'); print(c.bind())"
  ```

  `True` means the login will work.
- Usernames are lowercased and limited to `a-z 0-9 . _ -` before the bind.
- To make Mokapi look more like production, copy people from the real directory into a git-ignored LDIF:

  ```powershell
  uv run python scripts/export_ldap_to_mokapi.py <env-name> --login jdoe --with-managers
  ```

  Select people with `--login` (repeatable), `--logins-file` (one login per line) or `--filter` plus `--limit`;
  `--with-managers` also copies the manager chain. The script is read-only against the directory, writes
  `config/ldap-production.ldif` by default, refuses a path that git does not ignore and refuses to overwrite without
  `--force`. Production DNs look like `cn=<Full Name>,...`, so set `LDAP_USERNAME_PATTERN` to match them.

## 5. Create the tables and the permission rules

```powershell
uv run alembic -x env=dev upgrade head
```

Migrations that change a table need a database role that owns it; set `MIGRATIONS_DATABASE_URL` to the
owner's connection string if the normal user does not.

Logging in is not enough: every web action runs the real command as the LDAP user in the `$webui` channel, so
a [permission rule](PERMISSIONS.md) must allow it. `scripts/migrate_permissions.py` seeds the rules (set the
admin user there first); on an empty database the pages say "not allowed" until you have done it.

## 6. Run

```powershell
uv run python src/run_webapp.py dev     # web UI and REST API, auto-reloads on code changes
uv run python src/__main__.py dev       # the chat bot (needs a chat platform's variables)
```

Open `http://localhost:5709/` (or `/eurobot/`, see step 3). The REST API's interactive documentation is at
`/docs`.

The web UI runs fine without the bot, but requests only become real once someone approves them in chat.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `uv` fails building `pyyaml` | It picked a Python newer than 3.14. Use `uv sync --python 3.14`. |
| 400 "Invalid host header" | The host you typed is not in `WEBAPP_ALLOWED_HOSTS`. |
| 404 on every page | `WEBAPP_ROOT_PATH` is `/eurobot/` (the default); add the prefix to the URL. |
| Login always fails | Mokapi not running, wrong `LDAP_USERNAME_PATTERN`, or `LDAP_AUTHENTICATION_TYPE` is still `NTLM`. Run the check in step 4 and look at the web process's log. |
| `KeyError: 'LDAP_SERVER'` | The variable is missing from the instance file. |
| Pages say "not allowed" | No permission rule for your user in the `$webui` channel (step 5). |
| Onboarding commands are missing | `config/github.yml` does not exist, so the plugin was not loaded. |
| Missing library on startup | Run the `plugins.py requirements` line from step 2 again. |
