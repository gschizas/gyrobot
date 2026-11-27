import os
import unittest
from unittest import mock

os.environ.setdefault('APPROVAL_DATABASE_URL', 'postgresql://u:p@localhost/x')

from backend.crowd_config import CrowdSettings, LdapSettings
from backend.ldap_directory import LdapDirectory

SETTINGS = CrowdSettings(
    crowd_url='https://crowd.test/crowd',
    ldap=LdapSettings(server='ldap://x', search_base='DC=x', mail_domain='x.test'))


def entry(dn='', **attrs):
    return mock.Mock(entry_attributes_as_dict=attrs, entry_dn=dn)


def directory(*results):
    connection = mock.MagicMock()
    pending = list(results)

    def search(base, ldap_filter, attributes=None, **kwargs):
        connection.entries = pending.pop(0)
    connection.search.side_effect = search
    return LdapDirectory(SETTINGS, connection=connection), connection


ALICE = entry(name='Alice Smith', sAMAccountName='asmith', mail='Alice.Smith@x.test', givenName='ALICE', sn='smith')


class LdapDirectoryTest(unittest.TestCase):
    def test_login_lookup_normalises_names(self):
        ldap, _ = directory([ALICE])
        person = ldap.find_person('asmith')
        self.assertEqual((person.mail, person.first_name, person.last_name), ('alice.smith@x.test', 'Alice', 'Smith'))
        self.assertEqual(person.username, 'asmith')

    def test_greek_name_cross_check(self):
        greek = entry(name='A B', sAMAccountName='ab', mail='ab@x.test', givenName='ANNA-MARIA', sn='shinas',
                      extensionAttribute10='ΑΝΝΑ-ΜΑΡΙΑ|ΣΧΙΝΑΣ')
        ldap, _ = directory([greek])
        person = ldap.find_person('ab')
        self.assertEqual(person.display_name, 'Anna-Maria Shinas')
        self.assertTrue(person.name_mismatch)
        ldap, _ = directory([ALICE])
        self.assertFalse(ldap.find_person('asmith').name_mismatch)

    def test_greek_name_attribute_and_separator_are_configurable(self):
        settings = CrowdSettings(crowd_url='u', ldap=LdapSettings(
            'ldap://x', 'DC=x', 'x.test', greek_name_attribute='extensionAttribute3', greek_name_separator=';'))
        item = entry(name='A B', sAMAccountName='ab', mail='ab@x.test', givenName='Anna', sn='Schinas',
                     extensionAttribute3='ΑΝΝΑ;ΣΧΙΝΑΣ')
        connection = mock.MagicMock(entries=[item])
        person = LdapDirectory(settings, connection=connection).find_person('ab')
        self.assertFalse(person.name_mismatch)
        self.assertIn('extensionAttribute3', connection.search.call_args.kwargs['attributes'])

    def test_username_attribute_name_uses_cn(self):
        settings = CrowdSettings(crowd_url='u', ldap=LdapSettings('s', 'b', 'd', username_attribute='name'))
        connection = mock.MagicMock(entries=[ALICE])
        person = LdapDirectory(settings, connection=connection).find_person('asmith')
        self.assertEqual(person.username, 'alice smith')

    def test_manager_is_resolved_from_the_distinguished_name(self):
        bob = entry(dn='CN=Bob Jones,OU=x,DC=x', name='Bob Jones', sAMAccountName='bjones', mail='bob@x.test',
                    givenName='Bob', sn='Jones')
        alice = entry(dn='CN=Alice Smith,OU=x,DC=x', name='Alice Smith', sAMAccountName='asmith',
                      mail='alice@x.test', givenName='Alice', sn='Smith', manager='CN=Bob Jones,OU=x,DC=x')
        ldap, connection = directory([alice], [bob], [])
        person = ldap.find_person('asmith')
        self.assertEqual(person.manager_dn, 'CN=Bob Jones,OU=x,DC=x')
        manager = ldap.get_manager(person)
        self.assertEqual(manager.login, 'bjones')
        self.assertEqual(connection.search.call_args.args[0], 'CN=Bob Jones,OU=x,DC=x')
        self.assertIsNone(ldap.get_manager(manager))
        self.assertIsNone(ldap.get_manager(person))

    def test_falls_back_to_mail_domain(self):
        ldap, connection = directory([], [ALICE])
        self.assertIsNotNone(ldap.find_person('asmith'))
        self.assertIn('mail=asmith@x.test', connection.search.call_args.args[1])

    def test_filter_input_is_escaped(self):
        ldap, connection = directory([], [])
        ldap.find_person('a)(uid=*')
        self.assertNotIn(')(uid=*', connection.search.call_args_list[0].args[1])

    def test_ambiguous_raises_and_missing_is_none(self):
        ldap, _ = directory([ALICE, ALICE])
        with self.assertRaises(ValueError):
            ldap.find_person('a@x.test')
        ldap, _ = directory([])
        self.assertIsNone(ldap.find_person('a@x.test'))


if __name__ == '__main__':
    unittest.main()
