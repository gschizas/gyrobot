"""Read-only Bitbucket Server client: which repositories do a set of (Crowd) groups have access to.

Authenticates with the secret ``BITBUCKET_TOKEN`` (an HTTP access token, preferred) or else
``BITBUCKET_USERNAME`` / ``BITBUCKET_PASSWORD``. Listing permissions needs project-admin rights.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

import requests

from backend.secret_store import get_secret

PAGE_SIZE = 100
CACHE_TTL_SECONDS = 6 * 3600
PARALLEL_REQUESTS = 8


class BitbucketError(RuntimeError):
    pass


class BitbucketApi:
    def __init__(self, base_url: str, session: Optional[requests.Session] = None):
        self.base_url = base_url.rstrip('/')
        self.session = session or requests.Session()
        if session is None:
            token = get_secret('BITBUCKET_TOKEN')
            if token:
                self.session.headers['Authorization'] = f"Bearer {token}"
            else:
                self.session.auth = (get_secret('BITBUCKET_USERNAME', required=True),
                                     get_secret('BITBUCKET_PASSWORD', required=True))
        self.session.headers['Accept'] = 'application/json'
        self._cache: dict[str, tuple[float, list]] = {}

    def _values(self, path: str) -> list[dict]:
        """All items of a paged Bitbucket collection, cached for a few minutes."""
        cached = self._cache.get(path)
        if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        values, start = [], 0
        while True:
            response = self.session.get(f"{self.base_url}/rest/api/1.0/{path}",
                                        params={'start': start, 'limit': PAGE_SIZE})
            if not response.ok:
                raise BitbucketError(f"Bitbucket: {path} failed ({response.status_code}): {response.text[:200]}")
            data = response.json()
            values.extend(data.get('values', []))
            if data.get('isLastPage', True):
                break
            start = data['nextPageStart']
        self._cache[path] = (time.monotonic(), values)
        return values

    def _prefetch(self, paths: list[str]) -> None:
        """Fill the cache for ``paths`` using a few parallel requests (there can be hundreds)."""
        with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
            list(pool.map(self._values, paths))

    def repos_for_groups(self, groups: Iterable[str], inherited_groups: Iterable[str] = ()) -> list[dict]:
        """Projects (via ``groups`` plus ``inherited_groups``, e.g. parent groups) and repositories (via ``groups``)
        the groups have permissions on, as ``{url, title}`` sorted by title."""
        direct = set(groups)
        project_groups = direct | set(inherited_groups)
        projects = self._values('projects')
        self._prefetch([f"projects/{p['key']}/{suffix}" for p in projects for suffix in ('permissions/groups', 'repos')])
        repos = [(p['key'], r) for p in projects for r in self._values(f"projects/{p['key']}/repos")]
        self._prefetch([f"projects/{key}/repos/{r['slug']}/permissions/groups" for key, r in repos])
        found = {}
        for project in projects:
            if any(p['group']['name'] in project_groups
                   for p in self._values(f"projects/{project['key']}/permissions/groups")):
                found[project['links']['self'][0]['href']] = project['name']
        for key, repo in repos:
            if any(p['group']['name'] in direct
                   for p in self._values(f"projects/{key}/repos/{repo['slug']}/permissions/groups")):
                found[repo['links']['self'][0]['href']] = repo['name']
        return sorted(({'url': url, 'title': title} for url, title in found.items()),
                      key=lambda r: r['title'].lower())
