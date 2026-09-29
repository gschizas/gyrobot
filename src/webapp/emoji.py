"""Slack emoji code to Unicode emoji mapping.

Slack interprets emoji codes like :white_check_mark: as Unicode emoji in messages,
but the web UI displays them as raw text. This module provides a utility to convert
them for non-Slack interfaces.
"""

SLACK_EMOJI_MAP = {
    ':hourglass_flowing_sand:': '⏳',
    ':inbox_tray:': '📥',
    ':white_check_mark:': '✅',
    ':no_entry:': '🚫',
    ':x:': '❌',
}


def convert_slack_emoji(text: str) -> str:
    """Replace Slack emoji codes in text with their Unicode equivalents."""
    for code, emoji in SLACK_EMOJI_MAP.items():
        text = text.replace(code, emoji)
    return text
