"""Base class and registry for secret backends.

A backend answers one question: "what is the value of secret ``name``?". It returns ``None`` when it does not
hold that secret (so the next backend is tried) and raises :class:`SecretBackendError` when it could not even
look (locked agent, unreachable vault, ...). Backend-specific libraries are imported lazily, so only the
backends actually configured need their packages installed.

To add a backend: create a module in this package with a :class:`SecretBackend` subclass that sets ``type_name``,
decorate it with :func:`register_backend`, and import the module in ``__init__.py``.
"""
import re
from abc import ABC, abstractmethod
from typing import ClassVar, Dict, Optional, Type


class SecretBackendError(RuntimeError):
    """A backend could not be queried (as opposed to simply not having the secret)."""


# Secret names become file names, command arguments and vault keys; keep them boring.
_SAFE_NAME = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.\-/]*$')


def check_name(name: str, allow_slash: bool = False) -> None:
    if not _SAFE_NAME.match(name) or '..' in name or (not allow_slash and '/' in name):
        raise SecretBackendError(f"Invalid secret name {name!r}")


class SecretBackend(ABC):
    type_name: ClassVar[str]

    @abstractmethod
    def get(self, name: str) -> Optional[str]:
        """Return the secret's value, or None if this backend does not have it."""

    def describe(self) -> str:
        return self.type_name


BACKENDS: Dict[str, Type[SecretBackend]] = {}


def register_backend(cls: Type[SecretBackend]) -> Type[SecretBackend]:
    BACKENDS[cls.type_name] = cls
    return cls
