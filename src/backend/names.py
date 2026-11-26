"""People's names: Title Case and the Greek/Latin cross-check used for directory names.

The directory (Active Directory) holds a Latin name (``givenName``/``sn``) and, in ``extensionAttribute10``, the
Greek one, upper case and separated by a pipe (``GIVEN|SURNAME``). Both contain mistakes, so the Latin name is only
trusted when it agrees with the romanized (ISO 843) Greek one; otherwise callers flag it for a human to check.
"""
import re
import unicodedata

from romanize import romanize

# A word is split at spaces, dashes and apostrophes, each part is capitalized and the separators are kept
_SEPARATORS = re.compile(r"([\s\-'’]+)")


def title_case(text: str) -> str:
    """``anna-maria o'BRIEN`` -> ``Anna-Maria O'Brien``. Works for Latin and Greek."""
    parts = _SEPARATORS.split(' '.join((text or '').split()))
    return ''.join(part if _SEPARATORS.fullmatch(part) else part[:1].upper() + part[1:].lower() for part in parts)


def split_greek_name(value: str, separator: str = '|') -> tuple[str, str]:
    """``ΓΙΩΡΓΟΣ|ΣΧΙΖΑΣ`` -> (title case given name, surname). Missing parts are empty."""
    given, _, surname = (value or '').partition(separator)
    return title_case(given), title_case(surname)


def romanize_greek(text: str) -> str:
    """ISO 843 transcription of Greek text, in Title Case. Latin text passes through unchanged."""
    return title_case(romanize(text or ''))


def _fold(text: str) -> str:
    """Case, accent and spacing-insensitive form for comparing names."""
    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).casefold().replace(' ', '')


def names_agree(latin: str, greek: str) -> bool:
    """Whether ``latin`` is what romanizing ``greek`` gives. An absent Greek name cannot disagree."""
    if not (greek or '').strip():
        return True
    return _fold(latin) == _fold(romanize_greek(greek))
