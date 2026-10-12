from typing import Optional

from backend.secret_store.base import SecretBackend, SecretBackendError, check_name, register_backend


@register_backend
class KeyringBackend(SecretBackend):
    """The Python ``keyring`` library (Secret Service/KWallet on Linux, Credential Manager on Windows, ...).

    Needs ``pip install keyring``. On a headless Linux server the default backends usually need a D-Bus session
    and an unlocked keyring; configure a suitable backend (``keyrings.alt``, ``PYTHON_KEYRING_BACKEND``) first.
    """
    type_name = 'keyring'

    def __init__(self, service: str = 'gyrobot'):
        self.service = service

    def get(self, name: str) -> Optional[str]:
        check_name(name)
        try:
            import keyring
        except ImportError as e:
            raise SecretBackendError("the 'keyring' package is not installed (pip install keyring)") from e
        try:
            return keyring.get_password(self.service, name)
        except Exception as e:
            raise SecretBackendError(f"keyring lookup of {name} failed: {e}") from e

    def describe(self) -> str:
        return f"{self.type_name} ({self.service})"
