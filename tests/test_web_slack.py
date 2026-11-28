"""Slack onboarding web page: account details, member list and the form arguments."""
import os
import unittest
from datetime import datetime, timezone
from unittest import mock
from uuid import uuid4

os.environ.setdefault('WEBAPP_SESSION_SECRET', 'test-secret')
os.environ.setdefault('DATABASE_URL', 'postgresql://u:p@localhost/x')

from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from backend.accounts import Account, Provision
from backend.slack_directory import SlackUser
from webapp import main
from webapp.routers import web

ACCOUNT = Account(name='Alice Smith', primary_email='alice@x.test', team='team-a',
                  metadata={'additional_emails': ['alice@out.test']})


class SlackFormTest(unittest.TestCase):
    def setUp(self):
        web._slack_members.update(time=0.0, members=None)
        self.client = TestClient(main.app, base_url='http://localhost', follow_redirects=False)
        with mock.patch('webapp.routers.web.ldap_authenticate', return_value='bob'):
            self.client.post('/login', data={'username': 'bob', 'password': 'x'})

    def test_page_renders_the_pickers(self):
        text = self.client.get('/onboarding/slack').text
        self.assertIn('attachSlackPicker', text)
        self.assertIn('slack-members', text)

    def test_account_details_by_any_email(self):
        provision = Provision(account_id=uuid4(), resource='slack', status='active', data={'member_ids': ['U1AAAAA']},
                              created_at=datetime.now(timezone.utc))
        with mock.patch.object(web, 'find_account_by_any_email', return_value=ACCOUNT), \
                mock.patch.object(web, 'get_provision', return_value=provision):
            data = self.client.get('/onboarding/slack/account', params={'email': 'alice@out.test'}).json()
        self.assertEqual((data['found'], data['name'], data['team']), (True, 'Alice Smith', 'team-a'))
        self.assertEqual(data['additional_emails'], ['alice@out.test'])
        self.assertEqual(data['member_ids'], ['U1AAAAA'])

    def test_unknown_account(self):
        with mock.patch.object(web, 'find_account_by_any_email', return_value=None):
            self.assertEqual(self.client.get('/onboarding/slack/account', params={'email': 'x@y.test'}).json(),
                             {'found': False})

    def test_members_skip_bots_and_are_sorted(self):
        users = [SlackUser('U2BBBBB', 'Zoe', 'zoe@x.test'), SlackUser('UBOT111', 'Bot', '', is_bot=True),
                 SlackUser('U3CCCCC', 'Old', 'old@x.test', deleted=True), SlackUser('U1AAAAA', 'Alice', 'a@x.test')]
        with mock.patch.object(web, 'SlackDirectory') as directory:
            directory.return_value.list_users.return_value = users
            members = self.client.get('/onboarding/slack/members').json()['members']
        self.assertEqual([m['id'] for m in members], ['U1AAAAA', 'U2BBBBB', 'U3CCCCC'])

    def test_members_error_is_reported(self):
        with mock.patch.object(web, 'SlackDirectory', side_effect=RuntimeError('no token')):
            response = self.client.get('/onboarding/slack/members')
        self.assertEqual(response.status_code, 502)
        self.assertIn('no token', response.json()['error'])

    def test_users_page_lists_provisions(self):
        provision = Provision(account_id=uuid4(), resource='github', status='active', data={'username': 'alice-gh'})
        with mock.patch.object(web, 'list_accounts_with_provisions', return_value=[(ACCOUNT, [provision])]):
            text = self.client.get('/onboarding/users').text
        self.assertIn('alice@out.test', text)
        self.assertIn('alice-gh', text)

    def test_short_search_returns_nothing(self):
        with mock.patch.object(web, 'search_accounts') as search:
            self.assertEqual(self.client.get('/onboarding/slack/accounts', params={'q': 'a'}).json(), {'accounts': []})
        search.assert_not_called()


class BuildArgsTest(unittest.TestCase):
    def test_checkbox_values_and_text_fallback(self):
        form = FormData([('email', 'a@x.test'), ('member_ids', 'U1AAAAA'), ('member_ids', 'U2BBBBB, U1AAAAA')])
        self.assertEqual(web._build_args('slack', form), ['onboard', 'slack', 'a@x.test', 'U1AAAAA', 'U2BBBBB'])

    def test_no_members_is_rejected(self):
        self.assertIsNone(web._build_args('slack', FormData([('email', 'a@x.test')])))


if __name__ == '__main__':
    unittest.main()
