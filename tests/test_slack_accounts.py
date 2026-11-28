import unittest
from unittest import mock

from backend import slack_accounts
from backend.slack_directory import SlackUser


class ParseMemberIdTest(unittest.TestCase):
    def test_forms(self):
        for text in ('<@U12345678|bob>', '<@U12345678>', '@u12345678', 'U12345678', ' U12345678 '):
            self.assertEqual('U12345678', slack_accounts.parse_member_id(text), text)

    def test_rejects(self):
        for text in ('bob', 'bob@example.com', '<@bob>', ''):
            self.assertIsNone(slack_accounts.parse_member_id(text), text)


class LinkTest(unittest.TestCase):
    def test_merges_ids_and_records_emails(self):
        account = mock.Mock(id='a', primary_email='Jo@corp.example')
        provision = mock.Mock(data={'member_ids': ['U0000001A'], 'emails': ['jo@corp.example']})
        directory = mock.Mock()
        directory.get_user.side_effect = lambda m: SlackUser(m, 'Jo', 'jo@outsourcer.example') if m == 'U0000002B' else None
        with mock.patch.object(slack_accounts, 'get_or_create_account', return_value=account), \
                mock.patch.object(slack_accounts, 'get_provision', return_value=provision), \
                mock.patch.object(slack_accounts, 'add_additional_email') as add, \
                mock.patch.object(slack_accounts, 'set_provision_status') as save:
            outcome = slack_accounts.link('jo@corp.example', ['U0000001A', 'U0000002B', 'U0000003C'], directory)
        data = save.call_args.args[3]
        self.assertEqual(['U0000001A', 'U0000002B', 'U0000003C'], data['member_ids'])
        self.assertEqual(['jo@corp.example', 'jo@outsourcer.example'], data['emails'])
        add.assert_called_once_with('a', 'jo@outsourcer.example')
        self.assertEqual(['U0000002B', 'U0000003C'], outcome['added'])
        self.assertEqual(['U0000001A', 'U0000003C'], outcome['unresolved'])
