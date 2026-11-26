"""Active Directory lookups (people by login or email) used by the Crowd onboarding."""
from dataclasses import dataclass

import ldap3
from ldap3.utils.conv import escape_filter_chars

from backend.crowd_config import CrowdSettings, load_settings
from backend.names import names_agree, split_greek_name, title_case
from backend.secret_store import get_secret

ATTRIBUTES = ['name', 'sAMAccountName', 'mail', 'givenName', 'sn', 'extensionAttribute10']


@dataclass(frozen=True)
class Person:
    cn: str
    login: str
    mail: str
    first_name: str
    last_name: str
    username_attribute: str = 'samaccountname'
    greek_first_name: str = ''
    greek_last_name: str = ''

    @property
    def username(self) -> str:
        """The Crowd user name, per the configured attribute."""
        return (self.login if self.username_attribute == 'samaccountname' else self.cn).lower()

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def name_mismatch(self) -> bool:
        """Whether the Latin name disagrees with the romanized Greek one (the directory has mistakes)."""
        return not (names_agree(self.first_name, self.greek_first_name)
                    and names_agree(self.last_name, self.greek_last_name))



def _first(value) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ''
    return str(value or '').strip()


class LdapDirectory:
    def __init__(self, settings: CrowdSettings | None = None, connection=None):
        self.settings = settings or load_settings()
        self._connection = connection

    @property
    def connection(self):
        if self._connection is None:
            cfg = self.settings.ldap
            server = ldap3.Server(cfg.server, get_info=ldap3.NONE)
            self._connection = ldap3.Connection(
                server, user=get_secret('LDAP_BIND_USERNAME', required=True),
                password=get_secret('LDAP_BIND_PASSWORD', required=True),
                authentication=ldap3.NTLM if cfg.authentication == 'NTLM' else ldap3.SIMPLE,
                auto_bind=True, read_only=True)
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.unbind()
            self._connection = None

    def _search(self, ldap_filter: str) -> list[Person]:
        self.connection.search(self.settings.ldap.search_base, ldap_filter, attributes=ATTRIBUTES)
        people = []
        for entry in self.connection.entries:
            attrs = entry.entry_attributes_as_dict
            greek_first, greek_last = split_greek_name(_first(attrs.get('extensionAttribute10')))
            people.append(Person(
                cn=_first(attrs.get('name')), login=_first(attrs.get('sAMAccountName')),
                mail=_first(attrs.get('mail')).lower(),
                first_name=title_case(_first(attrs.get('givenName'))), last_name=title_case(_first(attrs.get('sn'))),
                username_attribute=self.settings.ldap.username_attribute,
                greek_first_name=greek_first, greek_last_name=greek_last))
        return people

    def find_people(self, query: str) -> list[Person]:
        """Find people by login or email address. Returns every match (callers must treat more than one as ambiguous)."""
        query = query.strip()
        if not query:
            return []
        if '@' in query:
            return self._search(f"(&(objectclass=person)(mail={escape_filter_chars(query)}))")
        login = escape_filter_chars(query)
        found = self._search(f"(&(objectclass=person)(samaccountname={login}))")
        if found:
            return found
        address = escape_filter_chars(f"{query}@{self.settings.ldap.mail_domain}")
        return self._search(f"(&(objectclass=person)(mail={address}))")

    def find_person(self, query: str) -> Person | None:
        """The single match for ``query``; ``None`` if there is none. Raises ``ValueError`` if ambiguous."""
        people = self.find_people(query)
        if len(people) > 1:
            raise ValueError(f"{query!r} matches {len(people)} people in the directory")
        return people[0] if people else None


def verify_person(query: str, settings: CrowdSettings | None = None) -> tuple[Person | None, str | None]:
    """Look ``query`` (email or login) up in the directory: ``(person, None)``, or ``(None, reason)``.

    Lookup problems (no config, server unreachable) raise, so callers can tell them from a wrong address.
    """
    directory = LdapDirectory(settings)
    try:
        person = directory.find_person(query)
    except ValueError as e:
        return None, f"{e}; use the email address."
    finally:
        directory.close()
    if not person:
        return None, f"{query} was not found in the directory."
    if not (person.mail and person.first_name and person.last_name and person.username):
        return None, f"The directory entry of {query} lacks a mail address or a name."
    return person, None
