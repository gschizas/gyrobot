"""OAuth2 client-credentials authentication for the REST API.

Clients are configured in a YAML file (``config/oauth2_clients.yml``, see
``config/oauth2_clients.example.yml``) mapping ``client_id`` to a plaintext
``secret`` (kept out of git, same convention as ``config/*.credentials.yml``).
A successful ``client_id``/``client_secret`` exchange at ``POST /api/oauth/token``
returns a signed, short-lived JWT bearer token that must be presented as an
HTTP bearer credential in the ``Authorization`` request header on subsequent calls.
"""
import secrets
import time

import jwt

from webapp.config import jwt_secret, load_oauth2_clients, token_ttl_seconds

ALGORITHM = 'HS256'


def validate_client_credentials(client_id: str, client_secret: str) -> bool:
    if not client_id or not client_secret:
        return False
    clients = load_oauth2_clients()
    client = clients.get(client_id)
    if not client:
        return False
    expected_secret = str(client.get('secret', ''))
    return secrets.compare_digest(expected_secret, client_secret)


def create_access_token(client_id: str) -> tuple[str, int]:
    ttl = token_ttl_seconds()
    now = int(time.time())
    payload = {'sub': client_id, 'iat': now, 'exp': now + ttl, 'scope': 'onboarding'}
    token = jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM)
    return token, ttl


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) if the token is invalid/expired."""
    return jwt.decode(token, jwt_secret(), algorithms=[ALGORITHM])
