"""Generic plugin loader for chat platforms and command modules.

This module knows **nothing** about individual plugins. Every plugin declares itself with a
literal ``PLUGIN`` dict at the top of its own module (or package ``__init__``)::

    PLUGIN = {
        'requires': ['KUDOS_DATABASE_URL'],        # all of these env vars must be set
        'requires_any': ['WEGO_EXE', 'WEATHER_URL'],  # at least one of these
        'dependencies': ['yfinance>=0.2.43'],      # pip requirements private to this plugin
        'priority': 10,                            # chat platforms only: order for ``chat: auto``
    }

The loader reads ``PLUGIN`` with :mod:`ast` **without importing the module**, so a plugin's
third-party imports only happen if it is actually enabled, its environment is satisfied and its
dependencies are installed. A submodule also inherits the declaration of its parent packages
(importing it imports them), and is skipped if a parent is.

Plugin names: ``chat/<name>.py`` -> ``<name>``; ``commands/a/b.py`` -> ``a.b``;
``commands/a/__init__.py`` -> ``a``. Modules without ``PLUGIN`` are plain helpers and are not loaded
by the loader (they get imported by the plugins that use them).

Optional overrides in ``config/plugins.yml``::

    chat: auto                  # auto (first available platform by priority) or a platform name
    commands:
      enable: [generic, roll]   # optional whitelist (a name also covers its submodules)
      disable: [weather]        # always off

``python src/plugins.py requirements`` prints the pip requirements of the plugins that would be
loaded with the current environment (e.g. ``... | uv pip install -r -``).
"""
import ast
import importlib
import importlib.metadata
import logging
import os
import pathlib
import threading
from dataclasses import dataclass, field
from types import ModuleType

from packaging.requirements import Requirement

logger = logging.getLogger('plugins')

CONFIG_FILE = pathlib.Path('config/plugins.yml')
SOURCE_FOLDER = pathlib.Path('src')
KINDS = {'chat': SOURCE_FOLDER / 'chat', 'commands': SOURCE_FOLDER / 'commands'}

_lock = threading.Lock()
_command_status: dict[str, str] | None = None
_chat_module: ModuleType | None = None


@dataclass
class Plugin:
    name: str
    module: str
    kind: str
    requires: list[str] = field(default_factory=list)
    requires_any: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    priority: int = 100

    def merged_with(self, parent: 'Plugin') -> 'Plugin':
        return Plugin(
            self.name, self.module, self.kind,
            parent.requires + self.requires,
            parent.requires_any + self.requires_any,
            parent.dependencies + self.dependencies,
            self.priority)

    def missing_environment(self) -> list[str]:
        missing = [name for name in self.requires if name not in os.environ]
        if self.requires_any and not any(name in os.environ for name in self.requires_any):
            missing.append(' or '.join(self.requires_any))
        return missing

    def missing_dependencies(self) -> list[str]:
        missing = []
        for text in self.dependencies:
            requirement = Requirement(text)
            try:
                installed = importlib.metadata.version(requirement.name)
            except importlib.metadata.PackageNotFoundError:
                missing.append(text)
                continue
            if not requirement.specifier.contains(installed, prereleases=True):
                missing.append(f"{text} (installed {installed})")
        return missing


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    from bot_framework.yaml_wrapper import yaml
    with CONFIG_FILE.open(encoding='utf8') as f:
        return dict(yaml.load(f) or {})


def _read_declaration(path: pathlib.Path) -> dict | None:
    """Return the literal top-level ``PLUGIN`` dict of a source file, or None if it has none."""
    try:
        tree = ast.parse(path.read_text(encoding='utf8'), filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError) as e:
        logger.warning(f"cannot read plugin declaration of {path}: {e}")
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PLUGIN' for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                logger.warning(f"PLUGIN in {path} must be a literal dict")
    return None


def _names_for(kind: str, path: pathlib.Path) -> tuple[str, str]:
    """(plugin name, dotted module) for a source file."""
    parts = list(path.relative_to(KINDS[kind]).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts), '.'.join([kind, *parts])


def discover(kind: str) -> dict[str, Plugin]:
    """All declared plugins of a kind, parent declarations merged into their submodules."""
    found: dict[str, Plugin] = {}
    for path in sorted(KINDS[kind].rglob('*.py')):
        declaration = _read_declaration(path)
        if declaration is None:
            continue
        name, module = _names_for(kind, path)
        if not name:
            continue
        found[name] = Plugin(
            name, module, kind,
            list(declaration.get('requires', [])),
            list(declaration.get('requires_any', [])),
            list(declaration.get('dependencies', [])),
            int(declaration.get('priority', 100)))
    for name in sorted(found, key=lambda n: n.count('.')):
        parent = name.rpartition('.')[0]
        while parent:
            if parent in found:
                found[name] = found[name].merged_with(found[parent])
                break
            parent = parent.rpartition('.')[0]
    return found


def _covers(names, name: str) -> bool:
    return any(name == n or name.startswith(n + '.') for n in names)


def _skip_reason(plugin: Plugin) -> str | None:
    if missing := plugin.missing_environment():
        return f"missing environment: {', '.join(missing)}"
    if missing := plugin.missing_dependencies():
        return f"missing packages: {', '.join(missing)}"
    return None


def load_command_plugins() -> dict[str, str]:
    """Import every enabled command plugin once. Returns ``{plugin: 'loaded' | reason it was skipped}``."""
    global _command_status
    with _lock:
        if _command_status is not None:
            return _command_status

        plugins = discover('commands')
        config = load_config().get('commands') or {}
        enable, disable = config.get('enable'), list(config.get('disable') or [])
        for name in set(enable or []) | set(disable):
            if name not in plugins:
                logger.warning(f"plugins.yml mentions unknown command plugin {name!r}")

        status: dict[str, str] = {}
        for name, plugin in plugins.items():
            if _covers(disable, name) or (enable is not None and not _covers(enable, name)):
                status[name] = 'disabled in config/plugins.yml'
            elif reason := _skip_reason(plugin):
                status[name] = reason
            else:
                status[name] = _import_plugin(plugin)
            logger.info(f"command plugin {name}: {status[name]}")
        _command_status = status
        return status


def _import_plugin(plugin: Plugin) -> str:
    try:
        importlib.import_module(plugin.module)
    except ImportError as e:
        logger.warning(f"command plugin {plugin.name} failed to import: {e}")
        return f"import failed: {e}"
    except Exception as e:
        logger.exception(f"command plugin {plugin.name} failed to load")
        return f"load failed: {e!r}"
    return 'loaded'


def select_chat_platform(check_packages: bool = True) -> Plugin:
    platforms = discover('chat')
    configured = load_config().get('chat', 'auto')
    skip_reason = _skip_reason if check_packages else (
        lambda p: f"missing environment: {', '.join(m)}" if (m := p.missing_environment()) else None)
    if configured != 'auto':
        if configured not in platforms:
            raise ValueError(f"Unknown chat platform {configured!r}; known: {', '.join(platforms)}")
        if reason := skip_reason(platforms[configured]):
            raise RuntimeError(f"Chat platform {configured!r}: {reason}")
        return platforms[configured]
    for plugin in sorted(platforms.values(), key=lambda p: (p.priority, p.name)):
        if not plugin.missing_environment():
            if reason := skip_reason(plugin):
                raise RuntimeError(f"Chat platform {plugin.name!r}: {reason}")
            return plugin
    raise NotImplementedError("Unknown chat protocol: no chat platform has its environment variables set")


def load_chat_platform() -> ModuleType:
    """Import (once) and return the selected chat platform module."""
    global _chat_module
    with _lock:
        if _chat_module is None:
            plugin = select_chat_platform()
            logger.info(f"chat platform: {plugin.name}")
            _chat_module = importlib.import_module(plugin.module)
        return _chat_module


def required_packages() -> list[str]:
    """pip requirements of the plugins that would load with the current environment and config."""
    config = load_config().get('commands') or {}
    enable, disable = config.get('enable'), list(config.get('disable') or [])
    requirements: dict[str, None] = {}
    try:
        requirements.update(dict.fromkeys(select_chat_platform(check_packages=False).dependencies))
    except (ValueError, RuntimeError, NotImplementedError):
        pass
    for name, plugin in discover('commands').items():
        if _covers(disable, name) or (enable is not None and not _covers(enable, name)):
            continue
        if not plugin.missing_environment():
            requirements.update(dict.fromkeys(plugin.dependencies))
    return list(requirements)


if __name__ == '__main__':
    import sys
    if len(sys.argv) in (2, 3) and sys.argv[1] == 'requirements':
        if len(sys.argv) == 3:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=f'.env.d/{sys.argv[2]}.env', override=True)
        print('\n'.join(required_packages()))
    else:
        sys.exit("usage: python src/plugins.py requirements [env-name]")
