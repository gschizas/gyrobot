import os
import unittest
from unittest import mock

os.environ.setdefault('APPROVAL_DATABASE_URL', 'postgresql://u:p@localhost/x')

from backend import crowd_api
from backend.crowd_config import CrowdSettings


class GroupTreeTest(unittest.TestCase):
    def setUp(self):
        crowd_api._TREE_CACHE.clear()
        settings = mock.Mock(spec=CrowdSettings)
        settings.crowd_url = 'https://crowd.test'
        self.api = crowd_api.CrowdApi(settings, session=mock.MagicMock())

    def _tree(self, groups, children):
        self.api.get_groups = lambda max_age=0: dict.fromkeys(groups, '')
        self.api.get_child_groups = lambda name: children.get(name, [])
        return self.api.build_group_tree()

    def test_multi_parent_filtered_child_and_cycle(self):
        tree = self._tree(['a', 'b', 'c', 'x', 'y'],
                          {'a': ['c', 'outside'], 'b': ['c'], 'x': ['y'], 'y': ['x']})
        roots = {node['value']: node for node in tree['children']}
        self.assertEqual(set(roots), {'a', 'b'})  # x and y only contain each other
        self.assertEqual([c['value'] for c in roots['a']['children']], ['c'])
        self.assertEqual([c['value'] for c in roots['b']['children']], ['c'])


if __name__ == '__main__':
    unittest.main()
