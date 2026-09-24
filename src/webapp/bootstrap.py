"""Bootstraps the Click command tree (``commands.gyrobot``) so it can be
driven programmatically, mirroring ``src/__main__.py``'s ``do_imports``.

Must run with the repository root as the current working directory (same
requirement as ``src/__main__.py``), since command modules glob/read files
relative to it (``config/``, ``data/``, ...).
"""
import importlib
import logging
import os
import threading
from glob import glob

logger = logging.getLogger('webapp.bootstrap')

_lock = threading.Lock()
_imported = False


def ensure_commands_imported() -> None:
    global _imported
    if _imported:
        return
    with _lock:
        if _imported:
            return
        for module_filename in glob('src/commands/**/*.py', recursive=True):
            module_without_folder = module_filename.removeprefix('src/')
            module_without_extension = os.path.splitext(module_without_folder)[0]
            module_name = module_without_extension.replace(os.path.sep, '.')
            try:
                importlib.import_module(module_name)
            except Exception as e:
                logger.info(f"Skipped {module_name}: {e}")
        _imported = True
