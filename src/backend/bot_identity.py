"""The bot's name and trigger words, defined once from the ``BOT_NAME`` environment variable.

Read lazily (not at import) because the environment may be loaded after modules are imported.
"""
import os

DEFAULT_BOT_NAME = 'Gyrobot'


def trigger_words(required: bool = False) -> list[str]:
    """All trigger words (``BOT_NAME`` split on whitespace); the first is the primary name.

    With ``required`` a missing ``BOT_NAME`` raises ``KeyError``; otherwise the default name is used.
    """
    value = os.environ['BOT_NAME'] if required else os.environ.get('BOT_NAME', '')
    return value.split() or [DEFAULT_BOT_NAME]


def bot_name() -> str:
    """The primary name, for use in messages and emails."""
    return trigger_words()[0]
