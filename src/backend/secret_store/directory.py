from pathlib import Path
from typing import Optional

from backend.secret_store.base import SecretBackend, SecretBackendError, check_name, register_backend


@register_backend
class DirectoryBackend(SecretBackend):
    """One file per secret in a directory (Docker/Kubernetes secrets mounted as files, for example).

    ``path``: the directory. ``lowercase``: also try the lower-case file name (``GITHUB_TOKEN`` -> ``github_token``).
    """
    type_name = 'directory'

    def __init__(self, path: str, lowercase: bool = True):
        self.directory = Path(path)
        self.lowercase = lowercase

    def _directory(self) -> Optional[Path]:
        return self.directory

    def get(self, name: str) -> Optional[str]:
        check_name(name)
        directory = self._directory()
        if directory is None:
            return None
        candidates = [name, name.lower()] if self.lowercase else [name]
        for candidate in dict.fromkeys(candidates):
            path = directory / candidate
            try:
                return path.read_text(encoding='utf-8').rstrip('\r\n')
            except FileNotFoundError:
                continue
            except OSError as e:
                raise SecretBackendError(f"Cannot read {path}: {e}") from e
        return None

    def describe(self) -> str:
        return f"{self.type_name} ({self.directory})"
