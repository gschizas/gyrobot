import os
import unittest
from unittest import mock

os.environ.setdefault('DATABASE_URL', 'postgresql://user:pw@localhost/none')  # engine is created lazily

from backend.accounts import Provision
from commands.onboarding import github


def _provision(status: str, **data) -> Provision:
    return Provision(account_id='a1', resource='github', status=status, data={'username': 'jdoe', **data})


class FindReinviteProvisionTest(unittest.TestCase):
    def find(self, provision, email='jdoe@example.com'):
        with mock.patch.object(github, 'extract_email', return_value=None), \
                mock.patch.object(github, 'find_account_by_any_email', return_value=mock.Mock(id='a1') if provision else None), \
                mock.patch.object(github, 'get_provision', return_value=provision):
            return github._find_reinvite_provision(mock.Mock(), {'email': email})

    def test_expired_cancelled_and_failed_can_be_reinvited(self):
        for status in ('expired', 'cancelled', 'failed'):
            found, error = self.find(_provision(status))
            self.assertIsNone(error, status)
            self.assertEqual(found.status, status)

    def test_pending_and_active_are_refused(self):
        for status in ('invited', 'active'):
            found, error = self.find(_provision(status))
            self.assertIsNone(found)
            self.assertIn('jdoe', error)

    def test_unknown_email_is_refused(self):
        found, error = self.find(None)
        self.assertIsNone(found)
        self.assertIn('No GitHub provision', error)


if __name__ == '__main__':
    unittest.main()
