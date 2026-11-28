"""Slack people by member id, through the Web API (``users.info`` / ``users.list``).

Used to find out which emails a Slack account signs in with, since a person may have several Slack accounts
(corporate and outsourcer addresses). Needs ``SLACK_BOT_TOKEN`` with the ``users:read`` and ``users:read.email``
scopes. The lookup also works from the web process and from scripts, which have no chat connection.
"""
import re
from dataclasses import dataclass

from slack_sdk import WebClient

from backend.secret_store import get_secret

MEMBER_ID = re.compile(r'[UW][A-Z0-9]{6,}')


@dataclass(frozen=True)
class SlackUser:
    id: str
    name: str
    email: str
    deleted: bool = False
    is_bot: bool = False


def _to_user(member: dict) -> SlackUser:
    profile = member.get('profile') or {}
    return SlackUser(
        id=member['id'], name=member.get('real_name') or profile.get('real_name') or member.get('name') or '',
        email=(profile.get('email') or '').strip().lower(), deleted=bool(member.get('deleted')),
        is_bot=bool(member.get('is_bot')))


class SlackDirectory:
    def __init__(self, client: WebClient | None = None):
        self._client = client

    @property
    def client(self) -> WebClient:
        if self._client is None:
            self._client = WebClient(token=get_secret('SLACK_BOT_TOKEN', required=True))
        return self._client

    def get_user(self, member_id: str) -> SlackUser | None:
        """The Slack user with ``member_id``; ``None`` if Slack does not know it."""
        from slack_sdk.errors import SlackApiError
        try:
            return _to_user(self.client.users_info(user=member_id)['user'])
        except SlackApiError as e:
            if e.response.get('error') == 'user_not_found':
                return None
            raise

    def list_users(self) -> list[SlackUser]:
        """Every member of the workspace (deactivated ones included), following the pagination."""
        users, cursor = [], None
        while True:
            response = self.client.users_list(limit=200, cursor=cursor)
            users.extend(_to_user(member) for member in response['members'])
            cursor = (response.get('response_metadata') or {}).get('next_cursor')
            if not cursor:
                return users
