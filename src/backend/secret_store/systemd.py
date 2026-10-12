import os
from pathlib import Path
from typing import Optional

from backend.secret_store.base import register_backend
from backend.secret_store.directory import DirectoryBackend


@register_backend
class SystemdCredentialsBackend(DirectoryBackend):
    """Credentials delivered by systemd (``LoadCredential=`` / ``LoadCredentialEncrypted=``).

    systemd exposes them as files in ``$CREDENTIALS_DIRECTORY``; the file name is the credential name.
    Nothing is found (and no error raised) when the process was not started with credentials.
    """
    type_name = 'systemd'

    def __init__(self, lowercase: bool = True):
        super().__init__(path='', lowercase=lowercase)

    def _directory(self) -> Optional[Path]:
        directory = os.environ.get('CREDENTIALS_DIRECTORY')
        return Path(directory) if directory else None

    def describe(self) -> str:
        return self.type_name
