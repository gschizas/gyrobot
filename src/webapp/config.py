"""Configuration helpers for the webapp package.

All settings are read from environment variables (loaded the same way as the
chat bot, via ``python-dotenv`` + ``.env.d/<name>.env``) plus, for OAuth2
clients, a YAML file analogous to the other ``config/*.yml`` files used
elsewhere in this project.
"""
import os
import pathlib
import threading
from typing import Optional

from bot_framework.yaml_wrapper import yaml

_clients_lock = threading.Lock()
_clients_cache: Optional[dict] = None


def oauth2_clients_config_path() -> pathlib.Path:
    env_value = os.environ.get('OAUTH2_CLIENTS_CONFIGURATION', 'config/oauth2_clients.yml')
    path = pathlib.Path(env_value)
    return path


def load_oauth2_clients(force_reload: bool = False) -> dict:
    """Load ``{client_id: {'secret': ..., 'description': ...}}`` from the
    OAuth2 clients YAML file (see ``config/oauth2_clients.example.yml``)."""
    global _clients_cache
    if _clients_cache is not None and not force_reload:
        return _clients_cache
    with _clients_lock:
        if _clients_cache is not None and not force_reload:
            return _clients_cache
        path = oauth2_clients_config_path()
        if not path.exists():
            raise RuntimeError(
                f"OAuth2 clients file {path} not found. Set OAUTH2_CLIENTS_CONFIGURATION "
                f"or create config/oauth2_clients.yml (see config/oauth2_clients.example.yml).")
        with path.open(encoding='utf8') as f:
            data = yaml.load(f) or {}
        _clients_cache = dict(data.get('clients') or {})
    return _clients_cache


def jwt_secret() -> str:
    try:
        return os.environ['WEBAPP_JWT_SECRET']
    except KeyError:
        raise RuntimeError("WEBAPP_JWT_SECRET not set - required to sign/verify API access tokens.")


def session_secret() -> str:
    try:
        return os.environ['WEBAPP_SESSION_SECRET']
    except KeyError:
        raise RuntimeError("WEBAPP_SESSION_SECRET not set - required to sign the web UI session cookie.")


def token_ttl_seconds() -> int:
    return int(os.environ.get('WEBAPP_TOKEN_TTL_SECONDS', '3600'))


def web_channel_name() -> str:
    return os.environ.get('WEBAPP_WEB_CHANNEL_NAME', '$webui')


def api_channel_name() -> str:
    return os.environ.get('WEBAPP_API_CHANNEL_NAME', '$api')


def web_team_name() -> str:
    return os.environ.get('WEBAPP_WEB_TEAM_NAME', 'webui')


def api_team_name() -> str:
    return os.environ.get('WEBAPP_API_TEAM_NAME', 'api')
