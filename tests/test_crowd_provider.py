import os
import unittest
from unittest import mock

os.environ.setdefault('APPROVAL_DATABASE_URL', 'postgresql://u:p@localhost/x')

from backend.accounts import Provision
from backend.crowd_config import CrowdSettings, LdapSettings
from backend.ldap_directory import Person
from backend.providers import crowd
from backend.providers.base import ProvisionRequest

SETTINGS = CrowdSettings(crowd_url='https://crowd.test', ldap=LdapSettings('s', 'b', 'x.test'))
PERSON = Person(cn='Alice Smith', login='asmith', mail='alice@x.test', first_name='Alice', last_name='Smith')
MANAGER = Person(cn='Bob Jones', login='bjones', mail='bob@x.test', first_name='Bob', last_name='Jones')


def request(team='', extra=()):
    return ProvisionRequest(name='a', email='alice@x.test', userid='asmith', team=team,
                            provision_data={'extra_groups': list(extra)})


class CrowdProviderTest(unittest.TestCase):
    def setUp(self):
        self.ctx = mock.Mock()
        self.api = mock.Mock()
        self.api.get_groups.return_value = {'team-a': '', 'team-b': '', 'extra': ''}
        self.api.get_user.return_value = None
        patches = [mock.patch.object(crowd, 'load_settings', return_value=SETTINGS),
                   mock.patch.object(crowd, '_find_person', return_value=PERSON),
                   mock.patch.object(crowd, 'generate_password', return_value='secret-words-42'),
                   mock.patch.object(crowd, 'send_email'),
                   mock.patch.object(crowd.bot_identity, 'bot_name', return_value='bot'),
                   mock.patch.object(crowd, '_find_manager', return_value=MANAGER),
                   mock.patch.object(crowd, 'resolve_teams', side_effect=lambda r, t: {'pay': ['team-a', 'team-b']}.get(t, []))]
        self.send_email = [p.start() for p in patches][3]
        self.addCleanup(mock.patch.stopall)

    def test_manager_gets_a_notice_without_the_password(self):
        message = crowd.provision(self.ctx, request('pay'), self.api)
        notice = [c for c in self.send_email.call_args_list if c.args[0] == 'crowd_manager_notice'][0]
        self.assertEqual(notice.kwargs['to'], 'bob@x.test')
        self.assertNotIn('password', notice.kwargs)
        self.assertNotIn('secret-words', str(notice))
        self.assertIn('bob@x.test', message)

    def test_manager_failures_never_fail_the_onboarding(self):
        for broken in ({'return_value': None}, {'side_effect': OSError('ldap down')}):
            with mock.patch.object(crowd, '_find_manager', **broken):
                crowd.provision(self.ctx, request('pay'), self.api)

    def test_new_user_gets_mapped_and_extra_groups_and_the_password_never_leaks(self):
        req = request('pay', ['extra'])
        message = crowd.provision(self.ctx, req, self.api)
        self.api.create_user.assert_called_once_with('asmith', 'Alice', 'Smith', 'alice@x.test', 'secret-words-42')
        self.assertEqual([c.args[1] for c in self.api.add_to_group.call_args_list], ['team-a', 'team-b', 'extra'])
        self.assertEqual(self.send_email.call_args_list[0].kwargs['password'], 'secret-words-42')
        self.assertNotIn('secret-words', message + str(req.provision_data))

    def test_given_names_override_the_directory(self):
        req = request()
        req.provision_data.update({'given_name': 'Alicia', 'surname': ''})
        crowd.provision(self.ctx, req, self.api)
        self.api.create_user.assert_called_once_with('asmith', 'Alicia', 'Smith', 'alice@x.test', 'secret-words-42')
        self.assertEqual(self.send_email.call_args.kwargs['first_name'], 'Alicia')

    def test_unmapped_team_and_unknown_group_create_nothing(self):
        for req in (request('nowhere'), request('', ['nope'])):
            with self.assertRaises(RuntimeError):
                crowd.provision(self.ctx, req, self.api)
        self.api.create_user.assert_not_called()

    def test_existing_user_with_other_email_is_refused(self):
        self.api.get_user.return_value = {'name': 'asmith', 'email': 'other@x.test', 'active': True}
        with self.assertRaises(RuntimeError):
            crowd.provision(self.ctx, request(), self.api)
        self.api.add_to_group.assert_not_called()

    def test_existing_inactive_user_is_reactivated_without_new_password(self):
        self.api.get_user.return_value = {'name': 'asmith', 'email': 'ALICE@x.test', 'active': False}
        crowd.provision(self.ctx, request('pay'), self.api)
        self.api.set_active.assert_called_once_with('asmith', True)
        self.api.create_user.assert_not_called()
        self.assertIsNone(self.send_email.call_args_list[0].kwargs['password'])

    def test_mail_failure_for_new_user_is_an_error(self):
        self.send_email.side_effect = OSError('smtp down')
        with self.assertRaises(RuntimeError) as cm:
            crowd.provision(self.ctx, request(), self.api)
        self.assertNotIn('secret-words', str(cm.exception))

    def test_change_team_swaps_team_groups_but_keeps_extras(self):
        provision = Provision.__new__(Provision)
        provision.data = {'username': 'asmith', 'team_groups': ['team-a', 'extra'], 'extra_groups': ['extra']}
        crowd.change_team(self.ctx, provision, ['team-b'], self.api)
        self.api.add_to_group.assert_called_once_with('asmith', 'team-b')
        self.api.remove_from_group.assert_called_once_with('asmith', 'team-a')
        self.assertEqual(provision.data['team_groups'], ['team-b'])

    def test_deprovision_removes_groups_then_deactivates(self):
        self.api.get_user.return_value = {'name': 'asmith'}
        self.api.get_user_groups.return_value = ['team-a', 'team-b']
        provision = Provision.__new__(Provision)
        provision.data = {'username': 'asmith'}
        crowd.deprovision(self.ctx, provision, self.api)
        self.assertEqual(self.api.remove_from_group.call_count, 2)
        self.api.set_active.assert_called_once_with('asmith', False)


if __name__ == '__main__':
    unittest.main()
