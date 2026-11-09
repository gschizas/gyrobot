"""LDAP authentication for the Web UI.

Authenticates a username/password pair by performing a direct LDAP simple
bind as that user (no service account required). Configure via:

* ``LDAP_SERVER`` the server name
* ``LDAP_USERNAME_PATTERN`` include the domain if needed, i.e. DOMAIN\\user
"""
import logging
import os
import re

import ldap3
from ldap3.core.exceptions import LDAPException

logger = logging.getLogger('webapp.auth_ldap')

VALID_USERNAME_RE = re.compile(r'[a-z0-9._-]+')


def _pattern_domain(username_pattern: str) -> str | None:
    """The domain of LDAP_USERNAME_PATTERN (``DOMAIN\\{}`` or ``{}@domain.corp``), if it has one."""
    if '\\' in username_pattern:
        return username_pattern.partition('\\')[0].lower()
    if '@' in username_pattern:
        return username_pattern.rpartition('@')[2].lower()
    return None


def _same_domain(typed: str, expected: str) -> bool:
    """``DOMAIN`` and ``domain.corp`` name the same domain when the first labels match."""
    return typed.lower().partition('.')[0] == expected.partition('.')[0]


def normalize_username(username: str, username_pattern: str | None = None) -> str | None:
    """Reduce ``DOMAIN\\user`` and ``user@domain.corp`` to the lowercase bare ``user``.

    Returns None if the name is empty, has characters outside ``[a-z0-9._-]`` (they would end up in the bind
    name) or carries a domain other than the one in ``username_pattern`` (default: LDAP_USERNAME_PATTERN).
    """
    username = username.strip()
    domain = None
    if '\\' in username:
        domain, _, username = username.rpartition('\\')
    elif '@' in username:
        username, _, domain = username.rpartition('@')
    username = username.strip().lower()

    expected = _pattern_domain(username_pattern if username_pattern is not None
                               else os.environ.get('LDAP_USERNAME_PATTERN', ''))
    if domain is not None and expected and not _same_domain(domain.strip(), expected):
        return None
    return username if VALID_USERNAME_RE.fullmatch(username) else None


def ldap_authenticate(username: str, password: str) -> str | None:
    """Return the normalized username (see :func:`normalize_username`) if ``username``/``password`` bind
    successfully against the configured LDAP server, else None. Never raises -- any LDAP/connection error is
    treated as a failed login."""
    username = normalize_username(username)
    if not username or not password:
        return None

    server_name = os.environ['LDAP_SERVER']
    username_pattern = os.environ['LDAP_USERNAME_PATTERN']
    authentication_type = os.environ.get('LDAP_AUTHENTICATION_TYPE', 'NTLM').upper()
    username_with_domain = username_pattern.format(username)

    try:
        server = ldap3.Server(server_name, get_info=ldap3.ALL)
        if authentication_type == 'NTLM':
            auth_type = ldap3.NTLM
        else:
            auth_type = ldap3.SIMPLE
        connection = ldap3.Connection(server, user=username_with_domain, password=password, authentication=auth_type)
        if not connection.bind():
            return None
        connection.unbind()
        return username
    except LDAPException as e:
        logger.warning(f"LDAP authentication failed for {username!r}", exc_info=True)
        return None

