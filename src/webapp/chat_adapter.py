"""A headless ``Conversation`` implementation used to drive chat-bot commands
(``commands.gyrobot``) from the Web UI / REST API instead of Slack/Mattermost.

Rather than sending anything anywhere, every ``send_*`` call just records a
structured message that callers (the web templates / JSON API responses) can
render however they like.
"""
from typing import Dict, List

from backend.constants import TableFormat
from chat.chat_wrapper import Conversation


class HeadlessConversation(Conversation):
    """In-memory stand-in for a chat ``Conversation``.

    ``user_id``/``channel_id``/``channel_name``/``team_id``/``team_name`` feed
    directly into ``check_security``/``requires_approval`` permission checks
    (see ``backend/configuration.py`` and ``backend/approval.py``), so callers
    should pass the authenticated identity (LDAP username or OAuth2 client_id)
    as ``user_id``, and a stable pseudo-channel (e.g. ``$webui``/``$api``) as
    ``channel_name`` so administrators can grant access via ``permission_rules``.
    """

    def __init__(self, *, bot_name: str, user_id: str, channel_name: str, team_name: str,
                team_id: str = None, channel_id: str = None):
        super().__init__(bot_name=bot_name, channel_id=channel_id or channel_name,
                          user_id=user_id, team_id=team_id or team_name)
        self.channel_name = channel_name
        self._team_name = team_name
        self.messages: List[dict] = []

    def send_text(self, text, is_error: bool = False, icon_emoji: str = None, channel=None) -> None:
        self.messages.append({'type': 'text', 'text': text, 'is_error': is_error})

    def send_table(self, title: str, table: List[Dict], table_format: TableFormat = TableFormat.TABLE) -> None:
        self.messages.append({'type': 'table', 'title': title, 'rows': table})

    def send_tables(self, title: str, tables: Dict[str, List[Dict]],
                    table_format: TableFormat = TableFormat.TABLE) -> None:
        self.messages.append({'type': 'tables', 'title': title, 'tables': tables})

    def send_ephemeral(self, text, blocks, is_error, icon_emoji):
        self.messages.append({'type': 'text', 'text': text, 'is_error': is_error, 'ephemeral': True})

    def send_file(self, file_data, title=None, filename=None, channel=None):
        self.messages.append({
            'type': 'file', 'title': title, 'filename': filename,
            'size': len(file_data) if file_data else 0,
        })

    def send_fields(self, text, fields):
        self.messages.append({'type': 'fields', 'text': text, 'fields': fields})

    def send_blocks(self, blocks):
        self.messages.append({'type': 'blocks', 'blocks': blocks})

    def get_user_info(self, user_id) -> Dict:
        return {'id': user_id, 'real_name': user_id, 'name': user_id}

    def get_team_info(self) -> Dict:
        return {'id': self.team_id, 'name': self._team_name}
