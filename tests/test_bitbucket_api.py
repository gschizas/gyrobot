import unittest
from unittest import mock

from backend.bitbucket_api import BitbucketApi


def page(values):
    response = mock.Mock(ok=True, status_code=200)
    response.json.return_value = {'values': values, 'isLastPage': True}
    return response


def link(url):
    return {'links': {'self': [{'href': url}]}}


class BitbucketApiTest(unittest.TestCase):
    def test_repos_via_project_and_repo_permissions(self):
        answers = {
            'projects': [{'key': 'P', 'name': 'Proj', **link('u/P')}, {'key': 'Q', 'name': 'Other', **link('u/Q')}],
            'projects/P/permissions/groups': [{'group': {'name': 'parent'}}],
            'projects/P/repos': [{'slug': 'r', 'name': 'Repo', **link('u/P/r')}],
            'projects/P/repos/r/permissions/groups': [{'group': {'name': 'team-a'}}],
            'projects/Q/permissions/groups': [{'group': {'name': 'nobody'}}],
            'projects/Q/repos': [{'slug': 's', 'name': 'Hidden', **link('u/Q/s')}],
            'projects/Q/repos/s/permissions/groups': [{'group': {'name': 'parent'}}],  # parents count for projects only
        }
        session = mock.MagicMock()
        session.get.side_effect = lambda url, params=None: page(answers[url.split('/rest/api/1.0/')[1]])
        api = BitbucketApi('https://bb.test/', session=session)
        repos = api.repos_for_groups(['team-a'], inherited_groups=['parent'])
        self.assertEqual(repos, [{'url': 'u/P', 'title': 'Proj'}, {'url': 'u/P/r', 'title': 'Repo'}])


if __name__ == '__main__':
    unittest.main()
