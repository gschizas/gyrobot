import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault('DATABASE_URL', 'postgresql://u:p@localhost/x')

from backend import manager
from backend.ldap_directory import Person


def person(mail, first='A', last='B', manager_dn=''):
    return Person(cn='x', login='x', mail=mail, first_name=first, last_name=last, manager_dn=manager_dn)


def account(metadata=None):
    return SimpleNamespace(id=1, name='Alice', primary_email='alice@x.test',
                           metadata=metadata or {'additional_emails': ['a@x.test']})


class RefreshManagerTest(unittest.TestCase):
    def setUp(self):
        update = mock.patch.object(manager, 'update_account', side_effect=lambda _id, metadata: SimpleNamespace(
            id=_id, primary_email='alice@x.test', metadata=metadata))
        self.update = update.start()
        self.addCleanup(update.stop)

    def refresh(self, acct, found):
        with mock.patch.object(manager, 'lookup_manager', return_value=found):
            return manager.refresh_manager(acct)

    def test_stores_the_manager_next_to_other_metadata(self):
        result = self.refresh(account(), (person('alice@x.test'), person('bob@x.test', 'Bob', 'Jones')))
        self.assertEqual(result.metadata, {'additional_emails': ['a@x.test'], 'manager_email': 'bob@x.test',
                                           'manager_name': 'Bob Jones'})

    def test_no_manager_removes_the_stored_one(self):
        acct = account({'manager_email': 'old@x.test', 'manager_name': 'Old'})
        self.assertEqual(self.refresh(acct, (person('alice@x.test'), None)).metadata, {})

    def test_unchanged_does_not_write(self):
        acct = account({'manager_email': 'bob@x.test', 'manager_name': 'Bob Jones'})
        self.refresh(acct, (person('alice@x.test'), person('bob@x.test', 'Bob', 'Jones')))
        self.update.assert_not_called()

    def test_unknown_person_and_directory_errors_keep_what_is_stored(self):
        acct = account({'manager_email': 'bob@x.test'})
        self.assertIs(self.refresh(acct, (None, None)), acct)
        with mock.patch.object(manager, 'lookup_manager', side_effect=OSError('down')):
            self.assertIs(manager.refresh_manager(acct), acct)
        self.update.assert_not_called()


class OffboardingNoticeTest(unittest.TestCase):
    def notify(self, recipients, stored):
        from commands import onboarding
        acct = account({'manager_email': stored} if stored else {})
        with mock.patch.object(onboarding, 'refresh_manager', return_value=acct), \
                mock.patch.object(onboarding, 'configured_recipients', return_value=recipients), \
                mock.patch.object(onboarding, 'send_email') as send:
            onboarding._notify_offboarding(mock.Mock(), acct, 'alice@x.test', [{'Resource': 'r', 'Result': 'ok'}])
        return send

    def test_goes_to_the_recipients_and_the_manager_once(self):
        send = self.notify(['hr@x.test', 'bob@x.test'], 'bob@x.test')
        self.assertEqual(send.call_args.kwargs['to'], ['hr@x.test', 'bob@x.test'])

    def test_nobody_to_tell_sends_nothing_and_errors_are_swallowed(self):
        self.notify([], None).assert_not_called()
        from commands import onboarding
        with mock.patch.object(onboarding, 'refresh_manager', side_effect=OSError('x')):
            onboarding._notify_offboarding(mock.Mock(), account(), 'a@x.test', [])


if __name__ == '__main__':
    unittest.main()
