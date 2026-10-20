"""Which email domains belong to the organisation.

``allowed_email_domains`` is read from ``config/github.yml`` (the key that already gated GitHub onboarding), so
that every resource uses the same list. An empty or absent list means "no restriction".
"""
import pathlib
from typing import Optional

from bot_framework.yaml_wrapper import yaml

CONFIG_FILE = pathlib.Path('config/github.yml')


def allowed_email_domains(config: Optional[dict] = None) -> list[str]:
    """The configured domains. Pass an already loaded ``github.yml`` as ``config`` to avoid re-reading it."""
    if config is None:
        if not CONFIG_FILE.exists():
            return []
        with CONFIG_FILE.open(encoding='utf8') as f:
            config = yaml.load(f) or {}
    return list(config.get('allowed_email_domains') or [])


def email_domain(email: str) -> str:
    return email.rsplit('@', 1)[-1].strip().lower()


def is_allowed_email(email: str, domains: Optional[list[str]] = None) -> bool:
    """True if the email's domain is allowed (or no domains are configured)."""
    if domains is None:
        domains = allowed_email_domains()
    return not domains or email_domain(email) in {d.lower() for d in domains}
