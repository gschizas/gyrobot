import os
import unittest
from unittest import mock

os.environ.setdefault('DATABASE_URL', 'postgresql://u:p@localhost/x')

from backend.ldap_directory import Person
from commands.onboarding import github as command

PERSON = Person(cn='Alice Smith', login='asmith', mail='alice@x.test', first_name='Alice', last_name='Smith')


class GithubDirectoryCheckTest(unittest.TestCase):
    def setUp(self):
        self.github = mock.Mock(ad_check_email_domains=['x.test'])

    def check(self, person=PERSON, error=None, **params):
        with mock.patch.object(command, 'verify_person', return_value=(person, error)) as verify:
            params = {'email': 'ASmith@x.test', **params}
            return command._check_directory(params, self.github), params, verify

    def test_directory_supplies_email_and_names(self):
        error, params, _ = self.check()
        self.assertIsNone(error)
        self.assertEqual((params['email'], params['given_name'], params['surname']),
                         ('alice@x.test', 'Alice', 'Smith'))

    def test_command_line_names_win(self):
        _, params, _ = self.check(given_name='Alicia', surname=None)
        self.assertEqual((params['given_name'], params['surname']), ('Alicia', 'Smith'))

    def test_unknown_person_is_rejected(self):
        error, _, _ = self.check(person=None, error='x was not found in the directory.')
        self.assertIn('not found', error)

    def test_lookup_failure_is_reported(self):
        with mock.patch.object(command, 'verify_person', side_effect=RuntimeError('no config')):
            error = command._check_directory({'email': 'a@x.test'}, self.github)
        self.assertIn('no config', error)

    def test_other_domains_are_not_checked(self):
        error, params, verify = self.check(email='someone@other.test')
        self.assertIsNone(error)
        verify.assert_not_called()
        self.assertNotIn('given_name', params)

    def test_summary_and_display_name(self):
        self.assertEqual(command._display_name('Alice', 'Smith'), 'Alice Smith')
        self.assertIsNone(command._display_name('Alice', None))
        summary = command._github_summary({'username': 'al', 'team': 't', 'given_name': 'Alice', 'surname': 'Smith'})
        self.assertIn('(Alice Smith)', summary)


if __name__ == '__main__':
    unittest.main()
