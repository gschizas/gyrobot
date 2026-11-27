"""Crowd web pages: directory verification of emails and the pages that use it."""
import os
import unittest
from unittest import mock

os.environ.setdefault('WEBAPP_SESSION_SECRET', 'test-secret')
os.environ.setdefault('APPROVAL_DATABASE_URL', 'postgresql://u:p@localhost/x')

from fastapi.testclient import TestClient

from backend.ldap_directory import Person
from webapp import main
from webapp.routers import web

ELENI = Person(cn='Helen C', login='hc', mail='hc@x.test', first_name='Helen', last_name='Christodoulou',
               greek_first_name='Ελενη', greek_last_name='Χριστοδουλου')
ALICE = Person(cn='Alice Smith', login='asmith', mail='alice@x.test', first_name='Alice', last_name='Smith')


class CheckEmailsTest(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.object(web, 'LdapDirectory'),
                   mock.patch.object(web, 'get_account_by_email', return_value=None),
                   mock.patch.object(web, 'verify_person', side_effect=self.verify)]
        for patch in patches:
            patch.start()
        self.addCleanup(mock.patch.stopall)

    @staticmethod
    def verify(query, settings=None, directory=None):
        people = {'hc': ELENI, 'asmith': ALICE}
        return (people[query], None) if query in people else (None, f'{query} was not found in the directory.')

    def test_names_expected_names_and_mismatch(self):
        results = web._check_crowd_emails(['hc', 'asmith', 'nobody'])
        self.assertEqual(results['hc']['status'], 'ok')
        self.assertTrue(results['hc']['mismatch'])
        self.assertEqual((results['hc']['expected_given_name'], results['hc']['expected_surname']),
                         ('Eleni', 'Christodoulou'))
        self.assertFalse(results['asmith']['mismatch'])
        self.assertEqual(results['asmith']['mail'], 'alice@x.test')
        self.assertEqual(results['nobody']['status'], 'not_found')

    def test_existing_crowd_user_is_reported(self):
        provision = mock.Mock(status='active', data={'username': 'asmith'})
        with mock.patch.object(web, 'get_account_by_email', return_value=mock.Mock(id=1)), \
                mock.patch.object(web, 'get_provision', return_value=provision):
            results = web._check_crowd_emails(['asmith'])
        self.assertEqual(results['asmith']['status'], 'already_onboarded')


class CrowdPagesTest(unittest.TestCase):
    def test_pages_render_and_bulk_passes_the_names_on(self):
        client = TestClient(main.app, base_url='http://localhost', follow_redirects=False)
        with mock.patch('webapp.routers.web.ldap_authenticate', return_value='bob'):
            client.post('/login', data={'username': 'bob', 'password': 'x'})
        self.assertEqual(client.get('/onboarding/crowd/bulk').status_code, 200)
        self.assertIn('attachCrowdVerification', client.get('/onboarding/crowd').text)
        with mock.patch('webapp.routers.web.run_bot_command', return_value=[]) as run:
            response = client.post('/onboarding/crowd/bulk', data={
                'email': ['a@x.test', 'b@x.test', ''], 'team': ['pay', 'pay', ''],
                'given_name': ['', 'Eleni', ''], 'surname': ['', '', '']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([c.args[0] for c in run.call_args_list],
                         [['onboard', 'crowd', 'a@x.test', 'pay'],
                          ['onboard', 'crowd', 'b@x.test', 'pay', '--given-name', 'Eleni']])

    def test_group_tree_is_offered_with_a_text_fallback(self):
        client = TestClient(main.app, base_url='http://localhost', follow_redirects=False)
        with mock.patch('webapp.routers.web.ldap_authenticate', return_value='bob'):
            client.post('/login', data={'username': 'bob', 'password': 'x'})
        tree = {'label': 'Crowd', 'value': None, 'children': [{'label': 'grp-a', 'value': 'grp-a', 'children': []}]}
        with mock.patch.object(web, 'CrowdApi') as api:
            api.return_value.build_group_tree.return_value = tree
            self.assertIn('grp-a', client.get('/onboarding/crowd').text)
            self.assertIn('browse-team', client.get('/onboarding/crowd/bulk').text)
        with mock.patch.object(web, 'CrowdApi', side_effect=RuntimeError('down')):
            page = client.get('/onboarding/crowd').text
        self.assertIn('Could not load the Crowd group list', page)


if __name__ == '__main__':
    unittest.main()
