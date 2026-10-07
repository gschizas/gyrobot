from typing import Callable

import plugins
from chat.chat_wrapper import ChatWrapper


def get_notification_sender(bot_name: str) -> Callable[[str, str], None]:
    """Return ``sender(channel, text)`` for the active chat platform (no command context needed)."""
    conversation_class = plugins.load_chat_platform().CONVERSATION_CLASS

    def sender(channel: str, text: str) -> None:
        conversation_class(bot_name, channel, None, None).send_text(text, channel=channel)

    return sender


def get_chat_wrapper(logger, bot_name: str, message_handler: Callable) -> ChatWrapper:
    """Build the wrapper for the platform selected in :mod:`plugins` (see ``config/plugins.yml``)."""
    connect = plugins.load_chat_platform().setup(logger, message_handler)
    return ChatWrapper(bot_name, message_handler, connect, logger)
