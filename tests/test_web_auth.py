"""Every web UI route is login-protected unless it is on purpose public."""
import os
import unittest
from unittest import mock

os.environ.setdefault('WEBAPP_SESSION_SECRET', 'test-secret')
os.environ.setdefault('DATABASE_URL', 'postgresql://u:p@localhost/x')

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from webapp import main

JSON_401 = {'/onboarding/github/validate-users', '/onboarding/github/missing-emails/status',
            '/onboarding/crowd/verify', '/onboarding/slack/accounts', '/onboarding/slack/account',
            '/onboarding/slack/members'}


class DenyByDefault(unittest.TestCase):
    def test_anonymous_requests_never_reach_a_handler(self):
        client = TestClient(main.app, base_url='http://localhost', follow_redirects=False)
        checked = 0
        routes = [*main.web.router.routes, *main.web.json_router.routes, *main.permissions.router.routes]
        for route in routes:
            if not isinstance(route, APIRoute):
                continue
            path = route.path.replace('{rule_id}', '1').replace('{action}', 'github')
            for method in route.methods:
                with mock.patch('webapp.routers.web.run_bot_command') as run:
                    response = client.request(method, path)
                self.assertFalse(run.called, f'{method} {path} ran a command')
                if route.path in JSON_401:
                    self.assertEqual(response.status_code, 401, f'{method} {path}')
                else:
                    self.assertIn(response.status_code, (302, 303), f'{method} {path}')
                    self.assertTrue(response.headers['location'].endswith('/login'), f'{method} {path}')
                checked += 1
        self.assertGreater(checked, 15)


if __name__ == '__main__':
    unittest.main()
