import os
from dataclasses import dataclass

import requests

BASE_URL = "https://account.jetbrains.com/api/v1"


@dataclass(frozen=True)
class JetBrainsTeam:
    id: str
    name: str
    total_licenses: int
    unassigned_licenses: int

    @property
    def slug(self):
        return self.name.split('(', 1)[0].strip().lower().replace(' ', '-')

    def __hash__(self) -> int:
        return hash(self.id)


class JetBrainsApi:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        token = os.environ['JETBRAINS_TOKEN']
        customer_code = os.environ['JETBRAINS_CUSTOMER_CODE']
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'X-Customer-Code': customer_code,
            'X-Api-Key': token,
            'Content-Type': 'application/json'
        })
        self._initialized = True

    def get_teams(self):
        """Get all teams for the customer.

        There's no actual way to get all teams from the JetBrains API, so we have to get all licenses and then get the teams from the licenses.
        """
        all_licenses = self.get_all_licenses()
        teams_raw = [dict(items) for items in {frozenset(lic['team'].items()) for lic in all_licenses}]
        for team in teams_raw:
            team['total_licenses'] = sum(1 for lic in all_licenses if lic.get('team') and lic['team']['id'] == team['id'])
            team['unassigned_licenses'] = sum(1 for lic in all_licenses if lic.get('team') and lic['team']['id'] == team['id'] and lic.get('isAvailableToAssign'))
        teams = [JetBrainsTeam(**team) for team in teams_raw]
        return sorted(teams, key=lambda x: x.name)

    def get_all_licenses(self):
        return self.get_licenses(product_code='II', assigned=None)

    def find_team(self, identifier: str) -> JetBrainsTeam:
        """The team whose name, id or slug is ``identifier`` (case-insensitive; name, then id, then slug).

        Raises ValueError if there is no such team or the match is ambiguous.
        """
        wanted = str(identifier).strip().lower()
        teams = self.get_teams()
        for matches in ([t for t in teams if t.name.lower() == wanted],
                        [t for t in teams if str(t.id) == wanted],
                        [t for t in teams if t.slug == wanted]):
            if len(matches) == 1:
                return matches[0]
            if matches:
                raise ValueError(f"JetBrains team '{identifier}' is ambiguous: {', '.join(t.name for t in matches)}")
        raise ValueError(f"JetBrains team '{identifier}' not found")

    def get_licenses(self, product_code: str = 'II', assigned: bool = None, assignee_email: str = None):
        """Get the customer's licenses, optionally only the assigned/free ones or those held by one user."""
        return self._get_pages(f"{BASE_URL}/customer/licenses", product_code, assigned, assignee_email)

    def get_assigned_licenses(self, email: str, product_code: str = 'II'):
        """The licenses currently assigned to ``email``."""
        return self.get_licenses(product_code=product_code, assigned=True, assignee_email=email)

    def get_team_licenses(self, team_id: str, product_code: str = 'II', assigned: bool = None):
        """Get all licenses of a team, optionally only the assigned/free ones."""
        return self._get_pages(f"{BASE_URL}/customer/teams/{team_id}/licenses", product_code, assigned)

    def assign_license(self, email: str, team_id: int, first_name: str = '', last_name: str = '',
                       product_code: str = 'II') -> str:
        """Assign a free license of ``team_id`` to ``email`` and return its license id.

        Raises RuntimeError if the team has no free license.
        """
        free = [lic for lic in self.get_team_licenses(team_id, product_code, assigned=False)
                if lic.get('isAvailableToAssign', True)]
        if not free:
            raise RuntimeError(f"No free JetBrains licenses left in team {team_id}")
        license_id = free[0]['licenseId']
        payload = {
            'contact': {'email': email, 'firstName': first_name, 'lastName': last_name},
            'includeOfflineActivationCode': True,
            'license': {'productCode': product_code, 'team': team_id},
            'licenseId': license_id,
            'sendEmail': True,
        }
        self._check(self.session.post(f"{BASE_URL}/customer/licenses/assign", json=payload))
        return license_id

    def revoke_licenses(self, email: str, product_code: str = 'II') -> list[str]:
        """Revoke the user's licenses for a product; returns the revoked license ids.

        JetBrains refuses (and revokes nothing) if any of them was assigned less than 30 days ago.
        """
        resp = self.session.post(f"{BASE_URL}/customer/licenses/revoke",
                                 params={'email': email, 'productCode': product_code})
        self._check(resp)
        return resp.json().get('licenseIds', [])

    def change_licenses_team(self, license_ids: list[str], target_team_id: int):
        """Transfer licenses to another team; ones that cannot be transferred silently stay where they are."""
        self._check(self.session.post(f"{BASE_URL}/customer/changeLicensesTeam",
                                      json={'licenseIds': license_ids, 'targetTeamId': target_team_id}))

    def _get_pages(self, url: str, product_code: str, assigned: bool | None, assignee_email: str = None):
        params = {'productCode': product_code, 'perPage': 100, 'assigneeEmail': assignee_email,
                  'assigned': None if assigned is None else str(assigned).lower()}  # None values are not sent
        results = []
        page = 1
        while True:
            resp = self.session.get(url, params={**params, 'page': page})
            self._check(resp)
            licenses_page = resp.json()
            if not licenses_page:
                break
            results.extend(licenses_page)
            page += 1
        return results

    @staticmethod
    def _check(resp: requests.Response):
        """Like raise_for_status, but with the API's own error code and description in the message."""
        if resp.ok:
            return
        try:
            error = resp.json()
            detail = f"{error.get('code', resp.status_code)}: {error.get('description', resp.reason)}"
        except ValueError:
            detail = f"{resp.status_code} {resp.reason}"
        raise requests.HTTPError(f"JetBrains API error {detail}", response=resp)
