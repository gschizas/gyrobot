import os
import unittest
from unittest import mock

os.environ.setdefault('APPROVAL_DATABASE_URL', 'postgresql://u:p@localhost/x')

from backend.crowd_config import CrowdSettings, LdapSettings
from backend.ldap_directory import Person
from commands.onboarding import crowd as command

SETTINGS = CrowdSettings(crowd_url='https://crowd.test', ldap=LdapSettings('s', 'b', 'x.test'))
PERSON = Person(cn='Alice Smith', login='asmith', mail='alice@x.test', first_name='Alice', last_name='Smith')


class RenderGroupTreeTest(unittest.TestCase):
    @staticmethod
    def node(name, *children):
        return {'label': name, 'value': name, 'children': list(children)}

    def setUp(self):
        n = self.node
        self.tree = {'label': 'Crowd', 'value': None,
                     'children': [n('a', n('shared', n('leaf'))), n('b', n('shared', n('leaf')))]}

    def test_multi_parent_is_marked_and_not_expanded_twice(self):
        self.assertEqual(command.render_group_tree(self.tree), [
            '|-- a', '|   `-- shared', '|       `-- leaf',
            '`-- b', '    `-- shared (*)'])

    def test_filter_keeps_ancestors_and_depth_limits(self):
        self.assertEqual(command.render_group_tree(self.tree, 'LEAF'),
                         ['|-- a', '|   `-- shared', '|       `-- leaf',
                          '`-- b', '    `-- shared (*)'])
        self.assertEqual(command.render_group_tree(self.tree, None, 1), ['|-- a ...', '`-- b ...'])


class CrowdValidateTest(unittest.TestCase):
    def setUp(self):
        self.directory = mock.Mock()
        self.directory.find_person.return_value = PERSON
        self.api = mock.Mock()
        self.api.get_groups.return_value = {'team-a': '', 'extra': ''}
        patches = {
            'load_settings': mock.patch.object(command, 'load_settings', return_value=SETTINGS),
            'LdapDirectory': mock.patch.object(command, 'LdapDirectory', return_value=self.directory),
            'CrowdApi': mock.patch.object(command, 'CrowdApi', return_value=self.api),
            'resolve_teams': mock.patch.object(command, 'resolve_teams',
                                               side_effect=lambda r, t: ['team-a'] if t == 'pay' else []),
            'get_account_by_email': mock.patch.object(command, 'get_account_by_email', return_value=None)}
        for patch in patches.values():
            patch.start()
        self.addCleanup(mock.patch.stopall)

    def validate(self, **overrides):
        params = {'user': 'asmith', 'team': 'pay', 'group': (), **overrides}
        return command._crowd_validate(params, mock.Mock()), params

    def test_valid_request_is_rewritten_to_the_directory_email(self):
        error, params = self.validate(group=('extra',))
        self.assertIsNone(error)
        self.assertEqual(params['user'], 'alice@x.test')

    def test_names_come_from_the_directory_unless_given(self):
        _, params = self.validate()
        self.assertEqual((params['given_name'], params['surname']), ('Alice', 'Smith'))
        _, params = self.validate(given_name=' Alicia ')
        self.assertEqual((params['given_name'], params['surname']), ('Alicia', 'Smith'))

    def test_rejections(self):
        self.assertIn('No Crowd group mapping', self.validate(team='nope')[0])
        self.assertIn('Unknown Crowd group', self.validate(group=('missing',))[0])
        self.directory.find_person.return_value = None
        self.assertIn('not found', self.validate()[0])
        self.directory.find_person.side_effect = ValueError('matches 2 people')
        self.assertIn('matches 2 people', self.validate()[0])


if __name__ == '__main__':
    unittest.main()
