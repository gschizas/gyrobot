import os
import subprocess
from typing import Optional

from backend.secret_store.base import SecretBackend, SecretBackendError, check_name, register_backend


@register_backend
class PassBackend(SecretBackend):
    """The standard Unix password manager (https://www.passwordstore.org/): GPG-encrypted files.

    ``prefix``: folder inside the store (secret ``GITHUB_TOKEN`` is read from ``<prefix>/GITHUB_TOKEN``).
    ``gnupghome`` / ``store_dir``: optional ``GNUPGHOME`` / ``PASSWORD_STORE_DIR`` for the ``pass`` process.
    ``first_line_only``: use only the first line (the ``pass`` convention for passwords; leave off for
    multi-line secrets such as private keys). ``lowercase``: look up the lower-case name.
    """
    type_name = 'pass'

    def __init__(self, prefix: str = '', command: str = 'pass', gnupghome: Optional[str] = None,
                 store_dir: Optional[str] = None, timeout: float = 15, first_line_only: bool = False,
                 lowercase: bool = False):
        self.prefix = prefix.strip('/')
        self.command = command
        self.timeout = timeout
        self.first_line_only = first_line_only
        self.lowercase = lowercase
        self.env = {}
        if gnupghome:
            self.env['GNUPGHOME'] = gnupghome
        if store_dir:
            self.env['PASSWORD_STORE_DIR'] = store_dir

    def get(self, name: str) -> Optional[str]:
        check_name(name)
        entry = '/'.join(part for part in (self.prefix, name.lower() if self.lowercase else name) if part)
        # stdin is closed so that a locked agent fails fast instead of waiting for a passphrase prompt
        try:
            result = subprocess.run([self.command, 'show', entry], capture_output=True, text=True,
                                    timeout=self.timeout, stdin=subprocess.DEVNULL, env={**os.environ, **self.env})
        except FileNotFoundError as e:
            raise SecretBackendError(f"'{self.command}' is not installed") from e
        except subprocess.TimeoutExpired as e:
            raise SecretBackendError(f"'{self.command} show {entry}' timed out (gpg-agent locked?)") from e
        if result.returncode != 0:
            if 'not in the password store' in result.stderr:
                return None
            raise SecretBackendError(f"'{self.command} show {entry}' failed: {result.stderr.strip()}")
        value = result.stdout.rstrip('\r\n')
        return value.splitlines()[0] if self.first_line_only and value else value

    def describe(self) -> str:
        return f"{self.type_name} ({self.prefix or '/'})"
