"""Platform-neutral extraction of command arguments.

Chat platforms decorate what users type (Slack turns an email into ``<mailto:a@b.c|a@b.c>``, for example). Each
conversation strips its own markup in ``Conversation.clean_argument``; commands only call the helpers here,
which add the shared validation.
"""
import re

from chat.chat_wrapper import ARGUMENT_EMAIL

_EMAIL = re.compile(r'[^@\s<>|()\[\]]+@[^@\s<>|()\[\]]+\.[^@\s<>|()\[\]]+')


def extract_email(ctx, text: str) -> str | None:
    """The bare email address in ``text`` as typed on ``ctx``'s platform, or None if it isn't one."""
    cleaned = ctx.chat.clean_argument(text, ARGUMENT_EMAIL).strip()
    return cleaned if _EMAIL.fullmatch(cleaned) else None
