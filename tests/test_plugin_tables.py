import os
import unittest
from unittest import mock

os.environ.setdefault('DATABASE_URL', 'postgresql://u:p@localhost/x')

import plugins
from plugins import Plugin


class RequiredTablesTest(unittest.TestCase):
    def test_reports_only_missing_tables(self):
        plugin = Plugin('x', 'commands.x', 'commands', requires_tables=['kudos', 'accounts'])
        with mock.patch.object(plugins, '_existing_tables', return_value={'accounts'}):
            self.assertEqual(plugin.missing_tables(), ['table kudos'])

    def test_no_tables_needs_no_database(self):
        with mock.patch.object(plugins, '_existing_tables', side_effect=AssertionError):
            self.assertEqual(Plugin('x', 'commands.x', 'commands').missing_tables(), [])

    def test_unreachable_database_skips_plugin(self):
        plugin = Plugin('x', 'commands.x', 'commands', requires_tables=['kudos'])
        with mock.patch.object(plugins, '_existing_tables', side_effect=OSError):
            self.assertEqual(plugin.missing_tables(), ['database unreachable (OSError)'])

    def test_parent_tables_are_inherited(self):
        parent = Plugin('a', 'commands.a', 'commands', requires_tables=['accounts'])
        child = Plugin('a.b', 'commands.a.b', 'commands', requires_tables=['roles'])
        self.assertEqual(child.merged_with(parent).requires_tables, ['accounts', 'roles'])


if __name__ == '__main__':
    unittest.main()
