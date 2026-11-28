import os
import unittest
from unittest import mock

os.environ.setdefault('DATABASE_URL', 'postgresql://u:p@localhost/x')

from backend import crowd_api
from backend.crowd_api import CrowdApi, CrowdError
from backend.crowd_config import CrowdSettings, LdapSettings

SETTINGS = CrowdSettings(
    crowd_url='https://crowd.test/crowd', directory_id=7, group_prefixes=('team-', 'ext-'),
    ldap=LdapSettings(server='ldap://x', search_base='DC=x', mail_domain='x.test'))


def response(status=200, body=None):
    r = mock.Mock(ok=status < 400, status_code=status, text=str(body))
    r.json.return_value = body
    return r


def api(session):
    return CrowdApi(SETTINGS, session=session)


class CrowdApiTest(unittest.TestCase):
    def test_get_user_missing_is_none(self):
        session = mock.MagicMock()
        session.get.return_value = response(404)
        self.assertIsNone(api(session).get_user('nobody'))

    def test_errors_raise(self):
        session = mock.MagicMock()
        session.get.return_value = response(500, {})
        with self.assertRaises(CrowdError):
            api(session).get_user('x')

    def test_list_users_pages(self):
        session = mock.MagicMock()
        with mock.patch.object(crowd_api, 'USER_PAGE_SIZE', 2):
            session.get.side_effect = [response(200, {'users': [{'name': 'a'}, {'name': 'b'}]}),
                                       response(200, {'users': [{'name': 'c'}]})]
            users = api(session).list_users()
        self.assertEqual([u['name'] for u in users], ['a', 'b', 'c'])
        self.assertEqual(session.get.call_args_list[1].kwargs['params']['start-index'], 2)

    def test_group_membership_conflicts_are_not_errors(self):
        session = mock.MagicMock()
        session.post.return_value = response(409, {})
        session.delete.return_value = response(404, {})
        crowd = api(session)
        crowd.add_to_group('u', 'team-a')
        crowd.remove_from_group('u', 'team-a')

    def test_groups_filtered_by_prefix_cached_and_described(self):
        session = mock.MagicMock()
        session.get.return_value = response(200,         {'groups': [
            {'name': 'team-b', 'description': 'Team  B\n(x)'}, {'name': 'other', 'description': ''},
                    {'name': 'team-a'}]})
        crowd = api(session)
        groups = crowd.get_groups()
        self.assertEqual(groups, {'team-a': '', 'team-b': 'Team B (x)'})
        crowd.get_groups()
        self.assertEqual(session.get.call_count, 1)  # a single page, then served from the cache

    def test_set_active_sends_the_whole_user_back(self):
        session = mock.MagicMock()
        session.get.return_value = response(200, {'name': 'u', 'active': True, 'email': 'e'})
        session.put.return_value = response(204, None)
        api(session).set_active('u', False)
        self.assertEqual(session.put.call_args.kwargs['json'], {'name': 'u', 'active': False, 'email': 'e'})


if __name__ == '__main__':
    unittest.main()
