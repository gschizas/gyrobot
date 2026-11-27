import os
import unittest
from unittest import mock

import click
from click.testing import CliRunner

from backend.cli import gyrobot_env


@click.command()
@click.option('--flag', is_flag=True)
@gyrobot_env
def sample(flag):
    click.echo(f"ran {flag}")


class GyrobotEnvTest(unittest.TestCase):
    def run_sample(self, args, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=False), \
                mock.patch('backend.cli.load_environment') as load:
            os.environ.pop('GYROBOT_ENV', None) if env is None else None
            result = CliRunner().invoke(sample, args)
        return result, load

    def test_argument_loads_the_environment(self):
        result, load = self.run_sample(['dev', '--flag'])
        self.assertEqual('ran True\n', result.output)
        load.assert_called_once_with('dev')

    def test_variable_is_the_default(self):
        result, load = self.run_sample([], env={'GYROBOT_ENV': 'prod'})
        self.assertEqual(0, result.exit_code)
        load.assert_called_once_with('prod')

    def test_missing_environment_is_an_error(self):
        result, load = self.run_sample([])
        self.assertEqual(2, result.exit_code)
        load.assert_not_called()
