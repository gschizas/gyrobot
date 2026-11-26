"""Client for the Atlassian Crowd REST API (users and groups).

Authenticates as the Crowd application in the secrets ``CROWD_USERNAME`` / ``CROWD_PASSWORD``. The ``admin`` API
refuses application credentials, so only ``usermanagement`` is used.
"""
import time
from typing import Optional

import requests

from backend.crowd_config import CrowdSettings, load_settings
from backend.secret_store import get_secret

USER_PAGE_SIZE = 500
GROUP_PAGE_SIZE = 500
GROUPS_TTL_SECONDS = 300
JSON = {'Accept': 'application/json', 'Content-Type': 'application/json'}


class CrowdError(RuntimeError):
    pass


class CrowdApi:
    def __init__(self, settings: Optional[CrowdSettings] = None, session: Optional[requests.Session] = None):
        self.settings = settings or load_settings()
        self.session = session or requests.Session()
        if session is None:
            self.session.auth = (get_secret('CROWD_USERNAME', required=True),
                                 get_secret('CROWD_PASSWORD', required=True))
        self.session.headers.update(JSON)
        self._groups: Optional[tuple[float, dict[str, str]]] = None

    @property
    def _users_url(self) -> str:
        return f"{self.settings.crowd_url}/rest/usermanagement/latest"

    def _check(self, response: requests.Response, what: str) -> requests.Response:
        if not response.ok:
            raise CrowdError(f"Crowd: {what} failed ({response.status_code}): {response.text[:200]}")
        return response

    def get_user(self, username: str) -> Optional[dict]:
        response = self.session.get(f"{self._users_url}/user", params={'username': username})
        if response.status_code == 404:
            return None
        return self._check(response, f"looking up user {username}").json()

    def list_users(self) -> list[dict]:
        """All users (``name``, ``email``, ``first-name``, ``last-name``, ``active``), fetched page by page."""
        users, start = [], 0
        while True:
            response = self._check(self.session.get(
                f"{self._users_url}/search",
                params={'entity-type': 'user', 'expand': 'user', 'start-index': start, 'max-results': USER_PAGE_SIZE}),
                "listing users")
            page = response.json().get('users', [])
            users.extend(page)
            if len(page) < USER_PAGE_SIZE:
                return users
            start += len(page)

    def create_user(self, name: str, first_name: str, last_name: str, email: str, password: str) -> None:
        self._check(self.session.post(f"{self._users_url}/user", json={
            'name': name, 'first-name': first_name, 'last-name': last_name, 'display-name': f"{first_name} {last_name}",
            'email': email, 'active': True, 'password': {'value': password}}), f"creating user {name}")

    def set_active(self, username: str, active: bool) -> None:
        """Activate or deactivate a user. Crowd's update replaces the whole user, so the current one is sent back."""
        user = self.get_user(username)
        if user is None:
            raise CrowdError(f"Crowd: user {username} does not exist")
        user['active'] = active
        user.pop('password', None)
        self._check(self.session.put(f"{self._users_url}/user", params={'username': username}, json=user),
                    f"updating user {username}")

    def get_user_groups(self, username: str) -> list[str]:
        response = self._check(self.session.get(f"{self._users_url}/user/group/direct", params={'username': username}),
                               f"listing the groups of {username}")
        return [g['name'] for g in response.json().get('groups', [])]

    def get_parent_groups(self, group: str) -> list[str]:
        """The groups that contain ``group``, directly or through nesting."""
        response = self._check(self.session.get(f"{self._users_url}/group/parent-group/nested",
                                                params={'groupname': group}), f"listing the parents of {group}")
        return [g['name'] for g in response.json().get('groups', [])]

    def add_to_group(self, username: str, group: str) -> None:
        response = self.session.post(f"{self._users_url}/user/group/direct", params={'username': username},
                                     json={'name': group})
        if response.status_code != 409:  # 409: already a member
            self._check(response, f"adding {username} to {group}")

    def remove_from_group(self, username: str, group: str) -> None:
        response = self.session.delete(f"{self._users_url}/user/group/direct",
                                       params={'username': username, 'groupname': group})
        if response.status_code != 404:  # 404: not a member
            self._check(response, f"removing {username} from {group}")

    def get_groups(self, max_age: float = GROUPS_TTL_SECONDS) -> dict[str, str]:
        """The assignable groups (names starting with one of ``group_prefixes``) as ``{name: description}``, cached.

        Uses the application-level group search: the ``admin`` API refuses application credentials.
        """
        if self._groups and time.monotonic() - self._groups[0] < max_age:
            return self._groups[1]
        prefixes = tuple(self.settings.group_prefixes) or ('',)
        groups, start = {}, 0
        while True:
            response = self._check(self.session.get(
                f"{self._users_url}/search",
                params={'entity-type': 'group', 'expand': 'group', 'start-index': start,
                        'max-results': GROUP_PAGE_SIZE}), "listing groups")
            page = response.json().get('groups', [])
            for group in page:
                if group['name'].startswith(prefixes):
                    groups[group['name']] = ' '.join(str(group.get('description') or '').split())
            if len(page) < GROUP_PAGE_SIZE:
                break
            start += len(page)
        self._groups = (time.monotonic(), dict(sorted(groups.items())))
        return self._groups[1]
