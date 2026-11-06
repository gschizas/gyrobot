"""Azure DevOps client: the user entitlements (who holds which access level) of one organisation.

``config/azdo.yml``::

    organization: my-org
    auth: pat                 # or "entra" (service principal)
    costs:                    # optional, per user per month, by access level name
      Basic: 6
      Stakeholder: 0

Credentials live in ``config/azdo.credentials.yml``: ``pat`` for ``auth: pat``, or ``tenant_id``,
``client_id`` and ``client_secret`` for ``auth: entra``. See docs/AZURE_DEVOPS.md.
"""
import pathlib
import threading
import time

import requests

from bot_framework.yaml_wrapper import yaml

ENTITLEMENTS_URL = 'https://vsaex.dev.azure.com/{organization}/_apis/userentitlements'
API_VERSION = '7.1'
# Well-known application id of Azure DevOps, used as the scope of Entra tokens
ENTRA_SCOPE = '499b84ac-1321-427f-aa17-267ca6975798/.default'
NEVER = '0001-01-01'


def _read_yaml(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding='utf-8') as f:
        return dict(yaml.load(f) or {})


class AzdoApi:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        config = _read_yaml(pathlib.Path('config/azdo.yml'))
        credentials = _read_yaml(pathlib.Path('config/azdo.credentials.yml'))
        self.organization = config['organization']
        self.auth = str(config.get('auth', 'pat')).lower()
        if self.auth not in ('pat', 'entra'):
            raise ValueError(f"config/azdo.yml: auth must be 'pat' or 'entra', not {self.auth!r}")
        self.credentials = credentials
        # Monthly price per user by lowercase access level name; levels without a price count as 0
        self.costs = {str(k).lower(): float(v) for k, v in (config.get('costs') or {}).items()}
        self._token: tuple[str, float] | None = None
        self._cache: tuple[float, list[dict]] | None = None
        self._lock = threading.Lock()
        self._initialized = True

    def _headers_and_auth(self) -> tuple[dict, tuple | None]:
        if self.auth == 'pat':
            return {}, ('', self.credentials['pat'])
        if not self._token or self._token[1] < time.time() + 60:
            resp = requests.post(
                f"https://login.microsoftonline.com/{self.credentials['tenant_id']}/oauth2/v2.0/token",
                data={'grant_type': 'client_credentials', 'client_id': self.credentials['client_id'],
                      'client_secret': self.credentials['client_secret'], 'scope': ENTRA_SCOPE}, timeout=30)
            resp.raise_for_status()
            body = resp.json()
            self._token = (body['access_token'], time.time() + int(body.get('expires_in', 3600)))
        return {'Authorization': f'Bearer {self._token[0]}'}, None

    @staticmethod
    def _member(item: dict) -> dict:
        user = item.get('user') or {}
        level = item.get('accessLevel') or {}
        last = (item.get('lastAccessedDate') or '')[:10]
        principal = user.get('principalName') or ''
        return {
            'id': item.get('id'),
            'email': (user.get('mailAddress') or principal).lower(),
            'principal_name': principal.lower(),
            'name': user.get('displayName') or '',
            'access_level': level.get('licenseDisplayName') or level.get('accountLicenseType') or 'Unknown',
            'license_type': level.get('accountLicenseType') or '',
            'licensing_source': level.get('licensingSource') or '',
            'assignment_source': level.get('assignmentSource') or '',
            'status': level.get('status') or '',
            'last_accessed': None if not last or last.startswith(NEVER) else last,
        }

    def _fetch(self) -> list[dict]:
        headers, auth = self._headers_and_auth()
        members, token = [], None
        while True:
            params = {'api-version': API_VERSION, 'top': 100}
            if token:
                params['continuationToken'] = token
            resp = requests.get(ENTITLEMENTS_URL.format(organization=self.organization), params=params,
                                headers=headers, auth=auth, timeout=60)
            # Azure DevOps answers a rejected token with a 203 and an HTML sign-in page
            if resp.status_code in (401, 203) or 'json' not in resp.headers.get('content-type', ''):
                raise RuntimeError("Azure DevOps rejected the credentials (check config/azdo.credentials.yml)")
            resp.raise_for_status()
            data = resp.json()
            members.extend(self._member(item) for item in data.get('items') or data.get('members') or [])
            token = data.get('continuationToken')
            if isinstance(token, list):
                token = token[0] if token else None
            if not token:
                return members

    def get_members(self, max_age: float = 300) -> list[dict]:
        """Every user entitlement as ``{id, email, principal_name, name, access_level, license_type,
        licensing_source, assignment_source, status, last_accessed}``.

        A result younger than ``max_age`` seconds is reused; pass 0 to force a fresh read.
        """
        with self._lock:
            if self._cache and time.time() - self._cache[0] < max_age:
                return self._cache[1]
            members = self._fetch()
            self._cache = (time.time(), members)
            return members
