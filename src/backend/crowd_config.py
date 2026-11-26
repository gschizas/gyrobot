"""Settings for the Crowd integration, read from ``config/crowd.yml`` (kept out of git: it holds site details).

Example::

    crowd_url: https://crowd.example.com/crowd       # without /rest
    group_prefixes: [team-, ext-]                    # which groups can be assigned
    ldap:
      server: ldap://ad.example.com
      search_base: DC=example,DC=com
      mail_domain: example.com                       # login -> login@mail_domain when matching by mail
      authentication: NTLM                           # or SIMPLE
      username_attribute: samaccountname             # Crowd user name taken from this attribute (or: name)
    welcome:                                         # optional, used by the welcome email
      portal_url: https://crowd.example.com/crowd/   # where users change their password
      hosts_note: If crowd.example.com does not resolve, use 10.0.0.1
      help_links:
        - {title: Common git push errors, url: https://wiki.example.com/push-errors}

The credentials are secrets (``backend.secret_store``): ``CROWD_USERNAME``/``CROWD_PASSWORD`` and
``LDAP_BIND_USERNAME``/``LDAP_BIND_PASSWORD``.
"""
import pathlib
from dataclasses import dataclass, field

from bot_framework.yaml_wrapper import yaml

CONFIG_PATH = pathlib.Path('config/crowd.yml')
USERNAME_ATTRIBUTES = ('samaccountname', 'name')


@dataclass(frozen=True)
class LdapSettings:
    server: str
    search_base: str
    mail_domain: str
    authentication: str = 'NTLM'
    username_attribute: str = 'samaccountname'


@dataclass(frozen=True)
class WelcomeSettings:
    """Site-specific values for the welcome email."""
    portal_url: str = ''
    help_links: tuple[dict, ...] = ()
    hosts_note: str = ''


@dataclass(frozen=True)
class CrowdSettings:
    crowd_url: str
    ldap: LdapSettings
    directory_id: int | None = None
    group_prefixes: tuple[str, ...] = field(default_factory=tuple)
    welcome: WelcomeSettings = field(default_factory=WelcomeSettings)


def load_settings(path: pathlib.Path = CONFIG_PATH) -> CrowdSettings:
    try:
        with open(path, encoding='utf-8') as f:
            raw = dict(yaml.load(f) or {})
    except OSError as e:
        raise RuntimeError(f"Cannot read {path}: {e}") from e
    try:
        ldap_raw = dict(raw['ldap'])
        ldap = LdapSettings(
            server=ldap_raw['server'], search_base=ldap_raw['search_base'], mail_domain=ldap_raw['mail_domain'],
            authentication=str(ldap_raw.get('authentication', 'NTLM')).upper(),
            username_attribute=str(ldap_raw.get('username_attribute', 'samaccountname')).lower())
        welcome_raw = dict(raw.get('welcome') or {})
        welcome = WelcomeSettings(
            portal_url=str(welcome_raw.get('portal_url', '')), hosts_note=str(welcome_raw.get('hosts_note', '')),
            help_links=tuple({'title': str(link['title']), 'url': str(link['url'])}
                             for link in welcome_raw.get('help_links') or ()))
        settings = CrowdSettings(
            crowd_url=str(raw['crowd_url']).rstrip('/'), ldap=ldap, welcome=welcome,
            directory_id=raw.get('directory_id'), group_prefixes=tuple(raw.get('group_prefixes') or ()))
    except KeyError as e:
        raise RuntimeError(f"{path}: missing setting {e}") from e
    if ldap.username_attribute not in USERNAME_ATTRIBUTES:
        raise RuntimeError(f"{path}: ldap.username_attribute must be one of {', '.join(USERNAME_ATTRIBUTES)}")
    if ldap.authentication not in ('NTLM', 'SIMPLE'):
        raise RuntimeError(f"{path}: ldap.authentication must be NTLM or SIMPLE")
    return settings
