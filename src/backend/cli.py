"""Helpers for the Click scripts in ``scripts/``."""
import functools
import os

import click

from backend.secret_store import ENVIRONMENT_VARIABLE, load_environment


def gyrobot_env(command):
    """Give a Click command the ``ENV_NAME`` argument (default: ``$GYROBOT_ENV``) and load that environment first.

    The command function does not receive the name; it is exported as ``GYROBOT_ENV`` for what needs it."""

    @click.argument('env_name', envvar=ENVIRONMENT_VARIABLE, metavar='ENV_NAME')
    @functools.wraps(command)
    def wrapper(env_name, *args, **kwargs):
        os.environ[ENVIRONMENT_VARIABLE] = env_name
        load_environment(env_name)
        return command(*args, **kwargs)

    return wrapper
