"""Smoke test of the OData router with the database and the permission rules mocked."""
import base64
import datetime
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('WEBAPP_SESSION_SECRET', 'x')
os.environ.setdefault('WEBAPP_JWT_SECRET', 'y')
_clients = tempfile.NamedTemporaryFile('w', suffix='.yml', delete=False)
_clients.write('clients:\n  reader:\n    secret: s3cret\n    scopes: [directory:read]\n'
               '  writer:\n    secret: w\n')
_clients.close()
os.environ['OAUTH2_CLIENTS_CONFIGURATION'] = _clients.name

from fastapi import FastAPI
from fastapi.testclient import TestClient

from webapp.routers import odata as router

ROW = {'Login': 'a', 'GithubId': 1, 'Email': 'a@x', 'Team': 'T1', 'Role': None, 'RoleName': None,
       'Status': 'active', 'LastChanged': datetime.datetime(2026, 1, 1), 'NodeId': 'MDQ6VXNlcjE='}
RULE = {'users': ['*'], 'channels': ['$api'], 'extra': {'team_prefixes': ['T']}}


def auth(client='reader', secret='s3cret'):
    return {'Authorization': 'Basic ' + base64.b64encode(f'{client}:{secret}'.encode()).decode()}


class ODataRouterTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router.router)
        self.client = TestClient(app, base_url='https://testserver')
        patcher = mock.patch.object(router.permissions, 'get_rule', return_value=RULE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_requires_auth(self):
        self.assertEqual(self.client.get('/api/odata/GithubUsers').status_code, 401)
        self.assertEqual(self.client.get('/api/odata/GithubUsers', headers=auth(secret='bad')).status_code, 401)

    def test_requires_scope(self):
        self.assertEqual(self.client.get('/api/odata/GithubUsers', headers=auth('writer', 'w')).status_code, 403)

    def test_basic_needs_https(self):
        plain = TestClient(self.client.app, base_url='http://testserver')
        self.assertEqual(plain.get('/api/odata/GithubUsers', headers=auth()).status_code, 403)

    def test_no_rule_denies(self):
        with mock.patch.object(router.permissions, 'get_rule', return_value=None):
            self.assertEqual(self.client.get('/api/odata/GithubUsers', headers=auth()).status_code, 403)

    def test_paging_and_count(self):
        with mock.patch.object(router.github_directory, 'list_github_users', return_value=[dict(ROW), dict(ROW)]) as lst, \
                mock.patch.object(router.github_directory, 'count_github_users', return_value=5):
            response = self.client.get('/api/odata/GithubUsers?$top=1&$count=true&$select=Login',
                                       headers=auth())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['value'], [{'Login': 'a'}])
        self.assertEqual(body['@odata.count'], 5)
        self.assertIn('skip=1', body['@odata.nextLink'])
        self.assertIn('$top=1', body['@odata.nextLink'].replace('%24', '$'))
        self.assertEqual(lst.call_args.args[2], 2)

    def test_links_keep_the_proxy_prefix(self):
        prefixed = TestClient(self.client.app, base_url='https://testserver', root_path='/eurobot')
        with mock.patch.object(router.github_directory, 'list_github_users', return_value=[dict(ROW), dict(ROW)]):
            body = prefixed.get('/api/odata/GithubUsers?$top=1', headers=auth()).json()
        self.assertTrue(body['@odata.nextLink'].startswith('https://testserver/eurobot/api/odata/GithubUsers?'))
        self.assertTrue(body['@odata.context'].startswith('https://testserver/eurobot/api/odata/'))

    def test_bad_filter_is_400(self):
        response = self.client.get('/api/odata/GithubUsers?$filter=Nope eq 1', headers=auth())
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_top_limit(self):
        self.assertEqual(self.client.get('/api/odata/GithubUsers?$top=1001', headers=auth()).status_code, 400)

    def test_metadata(self):
        response = self.client.get('/api/odata/$metadata', headers=auth())
        self.assertEqual(response.status_code, 200)
        self.assertIn('EntityType Name="GithubUser"', response.text)


if __name__ == '__main__':
    unittest.main()
