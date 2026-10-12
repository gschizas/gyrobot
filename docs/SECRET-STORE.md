# Secret store (`backend/secret_store`)

Pluggable lookup of secrets, so tokens and passwords need not sit in plain-text files. Background and the options
evaluated: `SECRETS-OPTIONS.md`, `SYSTEMD-CREDENTIALS.md`, `AZURE-KEY-VAULT.md`.

## Using it

```python
from backend.secret_store import get_secret

token = get_secret('GITHUB_TOKEN', required=True)   # raises SecretNotFound if missing
optional = get_secret('SOME_KEY', default=None)
```

Lookup order for `get_secret('NAME')`:

1. environment variable `NAME` (unless it is a `secret:` reference, see below)
2. the file whose path is in environment variable `NAME_FILE` (Docker/Kubernetes convention)
3. each backend in `config/secrets.yml`, in order (the first one that has the secret wins)

Found values are cached in memory for the life of the process (`clear_cache()` resets, `use_cache=False` bypasses).
A backend that cannot be queried (locked agent, vault unreachable) is logged as a warning and the next backend is
tried; if the secret is required and nothing has it, the error message lists those failures. Secret values are
never logged.

## Existing code: `secret:` references in `.env.d/*.env`

The entry points (`src/__main__.py`, `src/run_webapp.py`, `src/plugins.py requirements`) call
`load_environment(<env-name>)` instead of `load_dotenv`. It loads the env file as before and then resolves any value
that starts with `secret:`:

```
GITHUB_TOKEN=secret:                 # looks up the secret named GITHUB_TOKEN
GITHUB_APP_KEY=secret:github_app_key # looks up a differently named secret
BOT_NAME=eurobot                     # ordinary values are unchanged
```

All existing code that reads `os.environ['GITHUB_TOKEN']` keeps working, and plugin `requires` checks see the
variable as set. If a reference cannot be resolved, startup fails with a clear message rather than running
without the credential. Migrate secrets one at a time; plain values keep working.

## Configuration: `config/secrets.yml`

Path overridable with the environment variable `SECRETS_CONFIGURATION` (relative to `config/`, or absolute).
Without a config file, only the `systemd` backend is used (and it finds nothing unless started with credentials).

```yaml
backends:
  - type: systemd            # $CREDENTIALS_DIRECTORY (LoadCredential= / LoadCredentialEncrypted=)
  - type: pass
    prefix: gyrobot          # entries gyrobot/GITHUB_TOKEN, ...
    # gnupghome: /var/lib/gyrobot/.gnupg   store_dir: ...   first_line_only: false   timeout: 15
  - type: azure_keyvault
    vault_url: https://<vault>.vault.azure.net
    auth: default            # or: certificate (+ tenant_id, client_id, certificate_path)
  - type: keyring
    service: gyrobot
  - type: directory          # a folder with one file per secret, e.g. Docker secrets
    path: /run/secrets
```

| Type | Source | Extra package | Notes |
|---|---|---|---|
| `systemd` | files in `$CREDENTIALS_DIRECTORY` | none | file name = secret name (also tried lower-case) |
| `directory` | files in `path` | none | same naming as `systemd` |
| `pass` | `pass show <prefix>/<NAME>` | `pass`, `gnupg` (OS) | multi-line values kept unless `first_line_only` |
| `keyring` | `keyring.get_password(service, NAME)` | `keyring` | needs a usable keyring backend on a headless server |
| `azure_keyvault` | Key Vault secret `NAME` (`_` becomes `-`) | `azure-identity`, `azure-keyvault-secrets` | `auth: default` uses a managed identity, environment, `az login`, ... |

Backend libraries are imported only when that backend is used, so none are required by default.

## Adding a backend

Create a module in `backend/secret_store/` with a `SecretBackend` subclass that sets `type_name`, implements
`get(name) -> str | None` (return `None` if absent; raise `SecretBackendError` if the backend could not be
queried), decorate it with `@register_backend`, and import the module in `backend/secret_store/__init__.py`.
Constructor arguments become the options in `secrets.yml`. Validate names with `check_name`.

## Not done yet

- Only the entry points use `load_environment`; code that reads credentials from files (for example
  `config/*.credentials.yml`) does not go through the secret store yet.
- Rotation: values are cached for the life of the process, so a rotated secret needs a restart.
- No tests (the project has none yet); the backends were exercised with temporary files and a mocked `pass`.
