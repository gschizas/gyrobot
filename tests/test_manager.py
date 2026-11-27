import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault('APPROVAL_DATABASE_URL', 'postgresql://u:p@localhost/x')

from backend import manager
from backend.ldap_directory import Person


def person(mail, first='A', last='B', manager_dn=''):
    return Person(cn='x', login='x', mail=mail, first_name=first, last_name=last, manager_dn=manager_dn)


def account(metadata=None):
    return SimpleNamespace(id=1, primary_email='alice@x.test', metadata=metadata or {'additional_emails': ['a@x.test']})


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


if __name__ == '__main__':
    unittest.main()
