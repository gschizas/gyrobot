"""Bootstraps the Click command tree (``commands.gyrobot``) so it can be
driven programmatically, like ``src/__main__.py``'s ``do_imports``.

Which command modules are loaded is decided centrally by :mod:`plugins`
(registry + ``config/plugins.yml``).

Must run with the repository root as the current working directory (same
requirement as ``src/__main__.py``), since command modules read files
relative to it (``config/``, ``data/``, ...).
"""
import plugins


def ensure_commands_imported() -> None:
    plugins.load_command_plugins()
