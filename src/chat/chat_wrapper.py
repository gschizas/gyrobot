import base64
import datetime
import io
import logging
import re
import uuid
import zipfile
from abc import ABC, abstractmethod
from io import BytesIO
from typing import List, Dict, Callable

import click
import pandas as pd
from tabulate import tabulate

from backend.constants import TableFormat
from backend.excel import FormulaColumns, write_excel_table

# Kinds of argument a platform may decorate (see Conversation.clean_argument)
ARGUMENT_EMAIL = 'email'

_FENCED = re.compile(r'```\w*\n?(.*?)\n?```\s*', re.DOTALL)


def code_file_name(name: str | None = None) -> str:
    """File name for output sent as a file: ``<name>.<YYYYMMDD-HHMM>.txt``.

    Without ``name`` it is taken from the command being run (``github teams`` -> ``github-teams``).
    """
    if not name:
        context = click.get_current_context(silent=True)
        name = '-'.join(context.command_path.split()[1:]) if context else ''
    name = re.sub(r'[^\w.-]+', '-', name).strip('-.')
    return f"{name or 'output'}.{datetime.datetime.now():%Y%m%d-%H%M}.txt"


class Conversation(ABC):
    channel_id: str
    channel_name: str
    user_id: str
    team_id: str
    bot_name: str

    # Longest text the platform shows in one message; None means no limit (or no way to send a file instead).
    MAX_TEXT_LENGTH: int | None = None

    def __init__(self, bot_name, channel_id, user_id, team_id):
        self.bot_name = bot_name
        self.channel_id = channel_id
        self.user_id = user_id
        self.team_id = team_id

    def clean_argument(self, text: str, kind: str) -> str:
        """Strip this platform's markup from a command argument of the given kind (``ARGUMENT_*``).

        The default does nothing; platforms that decorate input override it. Must leave already-clean text as is.
        """
        return text.strip()

    @abstractmethod
    def send_text(self, text, is_error: bool = False, icon_emoji: str = None, channel=None) -> None:
        pass

    def overflow_to_file(self, text: str, channel=None) -> bool:
        """For ``send_text`` implementations: if ``text`` is longer than the platform allows, send it as a text file
        instead of letting it be split into broken messages, and return True."""
        if self.MAX_TEXT_LENGTH is None or len(text) <= self.MAX_TEXT_LENGTH:
            return False
        if fenced := _FENCED.fullmatch(text.strip()):
            text = fenced.group(1)
        self.send_file(text.encode(), title='Too long for a message, sent as a file',
                       filename=code_file_name(), channel=channel)
        return True

    def send_code(self, text: str, name: str | None = None, title: str | None = None, channel=None) -> None:
        """Send preformatted text. It is shown as a code block, or as a text file if too long for one message.

        ``name`` is the base of the file name (default: the running command, e.g. ``github-teams``); the date and
        time are added, giving ``github-teams.20261029-2006.txt``.
        """
        text = text.strip('\n')
        block = f"```\n{text}\n```"
        if self.MAX_TEXT_LENGTH is None or len(block) <= self.MAX_TEXT_LENGTH:
            self.send_text(block, channel=channel)
        else:
            self.send_file(text.encode(), title=title, filename=code_file_name(name), channel=channel)

    @abstractmethod
    def send_table(self, title: str, table: List[Dict], table_format: TableFormat = TableFormat.TABLE,
                   formula_columns: FormulaColumns | None = None) -> None:
        """formula_columns only affects Excel output (see backend.excel.write_excel_table)."""
        pass

    @abstractmethod
    def send_tables(self, title: str, tables: Dict[str, List[Dict]],
                    table_format: TableFormat = TableFormat.TABLE,
                    formula_columns: FormulaColumns | None = None) -> None:
        pass

    @abstractmethod
    def send_ephemeral(self, text, blocks, is_error, icon_emoji):
        pass

    @abstractmethod
    def send_file(self, file_data, title=None, filename=None, channel=None):
        pass

    @abstractmethod
    def send_fields(self, text, fields):
        pass

    @abstractmethod
    def send_blocks(self, blocks):
        pass

    @abstractmethod
    def get_user_info(self, user_id) -> Dict:
        pass

    @abstractmethod
    def get_team_info(self) -> Dict:
        pass

    @property
    def team_name(self) -> str:
        return self.get_team_info()['name']

    @staticmethod
    def make_excel_table(table, formula_columns: FormulaColumns | None = None):
        table_output: BytesIO
        with io.BytesIO() as table_output:
            table_df = pd.DataFrame(table)
            Conversation.localize_datetime(table_df)
            # noinspection PyTypeChecker
            with pd.ExcelWriter(table_output, engine='xlsxwriter') as writer:
                write_excel_table(writer, table_df, 'Sheet1', 'Table1', formula_columns)
            excel_data = table_output.getvalue()
        return excel_data

    @staticmethod
    def localize_datetime(table_df):
        dt_cols = table_df.select_dtypes(include=['datetime64[ns, UTC]']).columns
        for col in dt_cols:
            table_df[col] = table_df[col].dt.tz_localize(None)

    @staticmethod
    def plain_text_table_sequence(tables: Dict[str, List[Dict]]) -> str:
        def _cleanup(table: List[Dict]) -> List[Dict]:
            for row in table:
                for key, value in row.items():
                    if isinstance(value, bytes):
                        row[key] = value.decode(encoding='utf-8', errors='backslashreplace')
            return table

        result = ''
        for table_name, table in tables.items():
            table_markdown = tabulate(_cleanup(table), headers='keys', tablefmt='fancy_outline', maxcolwidths=64)
            # table_markdown = tabulate(table, headers='keys', tablefmt='pipe', maxcolwidths=30)
            table_length = len(table_name)
            result += "╒" + "═" * (2 + table_length) + "╕" + "\n"
            result += "│ " + table_name + " │\n"
            result += "╞" + table_markdown[1:3 + table_length] + "╧"
            result += table_markdown[4 + table_length:]
            result += "\n\n"
        return result

    @staticmethod
    def zipped_markdown_from_tables(tables):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for table_name, table in tables.items():
                table_markdown = tabulate(table, headers='keys', tablefmt='fancy_outline')
                zip_file.writestr(f"{table_name}.md", table_markdown.encode())
        zip_data = zip_buffer.getvalue()
        return zip_data

    @staticmethod
    def excel_from_tables(tables, formula_columns: FormulaColumns | None = None):
        excel_output: BytesIO
        with io.BytesIO() as excel_output:
            # noinspection PyTypeChecker
            with pd.ExcelWriter(excel_output, engine='xlsxwriter') as writer:
                long_sheet_names = []
                for table_index, (table_name, table) in enumerate(tables.items(), start=1):
                    if len(table_name) <= 31:
                        sheet_name = table_name
                    else:
                        sheet_name = Conversation.random_name()
                        long_sheet_names.append({'Original Name': table_name, 'Translated Name': sheet_name})
                    table_df = pd.DataFrame(table)
                    Conversation.localize_datetime(table_df)
                    write_excel_table(writer, table_df, sheet_name, f'Table{table_index}_{table_name}',
                                      formula_columns)
                if long_sheet_names:
                    write_excel_table(writer, pd.DataFrame(long_sheet_names), '__LongNames', 'LongNames')
            excel_output.seek(0)
            excel_data = excel_output.read()
        return excel_data

    @staticmethod
    def random_name() -> str:
        random_bytes = uuid.uuid4().bytes
        shorter_text = base64.b64encode(random_bytes)
        cleaned_up_text = shorter_text.strip(b'=').replace(b'/', b'.')
        return cleaned_up_text.decode()


class Message:
    conversation: Conversation
    timestamp: datetime.datetime
    permalink: str
    text: str

    def __init__(self, conversation: Conversation, timestamp: datetime.datetime, permalink: str, text: str):
        self.conversation = conversation
        self.timestamp = timestamp
        self.permalink = permalink
        self.text = text


class ChatWrapper(ABC):
    text_handler: Callable = None
    start_handler: Callable = None
    bot_name: str

    def __init__(self, bot_name: str, text_handler: Callable, start_handler: Callable, logger: logging.Logger):
        self.bot_name = bot_name
        self.text_handler = text_handler
        self.start_handler = start_handler
        self.logger = logger

    def start(self):
        self.start_handler(self.bot_name, self.handle_message)

    @staticmethod
    def handle_message(message: Message, logger: logging.Logger):
        try:
            ChatWrapper.text_handler(message)
        except Exception as ex:
            logger.exception(f"Error while handling message {message}: {ex!r}")
