"""Look up secrets (tokens, passwords, keys) from pluggable backends instead of plain-text files.

    from backend.secret_store import get_secret
    token = get_secret('GITHUB_TOKEN', required=True)

Lookup order for ``get_secret('NAME')``:

1. the environment variable ``NAME`` (unless it is a ``secret:`` reference, see below)
2. the file named by the environment variable ``NAME_FILE`` (Docker/Kubernetes secrets convention)
3. each backend configured in ``config/secrets.yml`` (or the path in ``SECRETS_CONFIGURATION``), in order

``config/secrets.yml``::

    backends:
      - type: systemd                 # $CREDENTIALS_DIRECTORY, from LoadCredential(Encrypted)=
      - type: pass
        prefix: gyrobot
      - type: azure_keyvault
        vault_url: https://<vault>.vault.azure.net
      - type: keyring
        service: gyrobot
      - type: directory               # e.g. Docker secrets
        path: /run/secrets

With no config file, only the ``systemd`` backend is used (when ``CREDENTIALS_DIRECTORY`` is set).

Existing code keeps reading ``os.environ``: :func:`load_environment` replaces ``load_dotenv`` at startup and
resolves env-file values of the form ``NAME=secret:`` (look up ``NAME``) or ``NAME=secret:other_name``, so the
plain-text value never has to be in ``.env.d/*.env``. Values are never logged.
"""
import logging
import os
import threading
from pathlib import Path
from typing import List, Optional

from dotenv import dotenv_values, load_dotenv

from backend.secret_store.base import BACKENDS, SecretBackend, SecretBackendError, register_backend
# Importing the modules registers the backends
from backend.secret_store import azure_keyvault, directory, keyring_store, pass_store, systemd  # noqa: F401

__all__ = ['get_secret', 'load_environment', 'clear_cache', 'SecretNotFound', 'SecretBackendError',
           'SecretBackend', 'register_backend']

REFERENCE_PREFIX = 'secret:'
logger = logging.getLogger('secret_store')

_lock = threading.Lock()
_backends: Optional[List[SecretBackend]] = None
_cache: dict = {}


class SecretNotFound(LookupError):
    pass


def _config_path() -> Optional[Path]:
    configured = os.environ.get('SECRETS_CONFIGURATION')
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else Path('config') / path
    default = Path('config') / 'secrets.yml'
    return default if default.exists() else None


def _build_backends() -> List[SecretBackend]:
    path = _config_path()
    if path is None:
        return [BACKENDS['systemd']()]
    from bot_framework.yaml_wrapper import yaml
    try:
        with open(path, encoding='utf-8') as f:
            config = yaml.load(f) or {}
    except OSError as e:
        raise SecretBackendError(f"Cannot read secrets configuration {path}: {e}") from e
    backends = []
    for entry in config.get('backends') or []:
        options = dict(entry)
        type_name = options.pop('type', None)
        if type_name not in BACKENDS:
            raise SecretBackendError(
                f"{path}: unknown backend type {type_name!r} (known: {', '.join(sorted(BACKENDS))})")
        try:
            backends.append(BACKENDS[type_name](**options))
        except (TypeError, ValueError) as e:
            raise SecretBackendError(f"{path}: bad options for backend {type_name!r}: {e}") from e
    return backends


def _get_backends() -> List[SecretBackend]:
    global _backends
    with _lock:
        if _backends is None:
            _backends = _build_backends()
        return _backends


def clear_cache() -> None:
    """Forget cached values and re-read the configuration on next use (for tests and secret rotation)."""
    global _backends
    with _lock:
        _cache.clear()
        _backends = None


def _lookup(name: str, use_cache: bool = True) -> tuple[Optional[str], list]:
    if use_cache and name in _cache:
        return _cache[name], []

    value = os.environ.get(name)
    if value and not value.startswith(REFERENCE_PREFIX):
        return value, []

    if file_path := os.environ.get(f'{name}_FILE'):
        try:
            return Path(file_path).read_text(encoding='utf-8').rstrip('\r\n'), []
        except OSError as e:
            return None, [f"{name}_FILE ({file_path}): {e}"]

    problems = []
    for backend in _get_backends():
        try:
            value = backend.get(name)
        except SecretBackendError as e:
            logger.warning(f"Secret backend {backend.describe()} failed for {name}: {e}")
            problems.append(f"{backend.describe()}: {e}")
            continue
        if value is not None:
            _cache[name] = value
            return value, problems
    return None, problems


def get_secret(name: str, default: Optional[str] = None, *, required: bool = False,
               use_cache: bool = True) -> Optional[str]:
    """Return the secret ``name``, or ``default``; raise :class:`SecretNotFound` if ``required`` and missing."""
    value, problems = _lookup(name, use_cache)
    if value is not None:
        return value
    if required:
        detail = f" ({'; '.join(problems)})" if problems else ''
        raise SecretNotFound(f"Secret {name} not found in the environment or any configured backend{detail}")
    return default


def load_environment(env_name: str, *, dotenv_path: Optional[str] = None) -> None:
    """Load ``.env.d/<env_name>.env`` into ``os.environ`` and resolve ``secret:`` references in it.

    Drop-in replacement for ``load_dotenv(dotenv_path=f'.env.d/{env_name}.env', override=True)``.
    Raises :class:`SecretNotFound` if a reference cannot be resolved, so the bot fails at startup rather than
    running without a credential.
    """
    path = dotenv_path or f'.env.d/{env_name}.env'
    load_dotenv(dotenv_path=path, override=True)
    for key, value in dotenv_values(path).items():
        if value is None or not value.startswith(REFERENCE_PREFIX):
            continue
        secret_name = value[len(REFERENCE_PREFIX):].strip() or key
        # The variable still holds the reference at this point, so a self-reference goes to the backends
        resolved, problems = _lookup(secret_name)
        if resolved is None:
            detail = f" ({'; '.join(problems)})" if problems else ''
            raise SecretNotFound(f"{path}: {key} refers to secret {secret_name!r}, which was not found{detail}")
        os.environ[key] = resolved
