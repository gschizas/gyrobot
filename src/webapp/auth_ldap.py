"""LDAP authentication for the Web UI.

Authenticates a username/password pair by performing a direct LDAP simple
bind as that user (no service account required). Configure via:

* ``LDAP_SERVER_URL`` -- e.g. ``ldaps://ldap.example.com`` or ``ldap://ldap.example.com``
* ``LDAP_BIND_DN_TEMPLATE`` -- a DN template with a ``{username}`` placeholder,
  e.g. ``uid={username},ou=People,dc=example,dc=com`` or, for Active Directory,
  ``{username}@example.com``.
"""
import logging
import os

import ldap3
from ldap3.core.exceptions import LDAPException

logger = logging.getLogger('webapp.auth_ldap')


def ldap_authenticate(username: str, password: str) -> bool:
    """Return True iff ``username``/``password`` bind successfully against the
    configured LDAP server. Never raises -- any LDAP/connection error is
    treated as a failed login."""
    if not username or not password:
        return False

    server_name = os.environ['LDAP_SERVER']
    username_pattern = os.environ['USERNAME_PATTERN']
    username_with_domain = username_pattern.format(username)

    try:
        server = ldap3.Server(server_name, get_info=ldap3.ALL)
        connection = ldap3.Connection(server, user=username_with_domain, password=password, authentication=ldap3.NTLM)
        if not connection.bind():
            return False
        connection.unbind()
        return True
    except LDAPException as e:
        logger.warning(f"LDAP authentication failed for {username!r}", exc_info=True)
        return False
