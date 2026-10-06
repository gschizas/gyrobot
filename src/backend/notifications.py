"""Chat notifications for backend events that have no command context.

Backend code (e.g. the background GitHub invitation check) has no ``ctx.chat``
to reply to, so it calls :func:`notify` instead. The chat platform registers
the actual sender once at startup with :func:`set_sender`. Messages go to the
approval notifications channel (see ``backend.approval._notify_channel``).

Notifications are best-effort: :func:`notify` never raises.
"""
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_sender: Optional[Callable[[str, str], None]] = None


def set_sender(sender: Optional[Callable[[str, str], None]]) -> None:
    """Register ``sender(channel, text)``; pass ``None`` to disable."""
    global _sender
    _sender = sender


def notify(text: str) -> bool:
    """Send ``text`` to the notifications channel. Returns True if it was sent."""
    if _sender is None:
        logger.debug("No notification sender registered; dropping: %s", text)
        return False
    try:
        from backend.approval import _notify_channel
        channel = _notify_channel()
        if not channel:
            logger.debug("No notification channel configured; dropping: %s", text)
            return False
        _sender(channel, text)
        return True
    except Exception:
        logger.exception("Failed to send notification")
        return False
