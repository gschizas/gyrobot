"""The manager of a person, read from the directory and remembered on the account.

The directory is the source of truth: ``refresh_manager`` re-reads it and stores the result in
``accounts.metadata`` (``manager_email``, ``manager_name``); the stored copy is what the notifications use when the
directory cannot be reached.
"""
import logging

from backend.account_storage import update_account
from backend.accounts import Account
from backend.ldap_directory import LdapDirectory, Person

logger = logging.getLogger(__name__)

EMAIL_KEY = 'manager_email'
NAME_KEY = 'manager_name'


def lookup_manager(email: str, directory: LdapDirectory | None = None) -> tuple[Person | None, Person | None]:
    """``(person, manager)`` for ``email``; either is ``None`` when the directory has no such entry."""
    own = directory is None
    directory = directory or LdapDirectory()
    try:
        person = directory.find_person(email)
        return person, (directory.get_manager(person) if person else None)
    finally:
        if own:
            directory.close()


def stored_manager_email(account: Account) -> str | None:
    return account.metadata.get(EMAIL_KEY) or None


def refresh_manager(account: Account, directory: LdapDirectory | None = None) -> Account:
    """Re-read the manager of ``account`` from the directory and store it; best effort.

    An account the directory does not know is left alone, and so is one when the directory cannot be reached.
    A person without a manager has the stored one removed.
    """
    try:
        person, manager = lookup_manager(account.primary_email, directory)
    except Exception as e:
        logger.warning(f"Could not read the manager of {account.primary_email}: {e!r}")
        return account
    if person is None:
        return account
    metadata = {key: value for key, value in account.metadata.items() if key not in (EMAIL_KEY, NAME_KEY)}
    if manager and manager.mail:
        metadata[EMAIL_KEY] = manager.mail
        metadata[NAME_KEY] = manager.display_name
    if metadata == account.metadata:
        return account
    return update_account(account.id, metadata=metadata) or account
