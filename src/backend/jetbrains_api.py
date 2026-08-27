import os
from dataclasses import dataclass

import requests

BASE_URL = "https://account.jetbrains.com/api/v1"


@dataclass(frozen=True)
class JetBrainsTeam:
    id: str
    name: str

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
        teams = set()
        all_licenses = self.get_all_licenses()
        for license in all_licenses:
            if 'team' in license and license['team']:
                teams.add(JetBrainsTeam(id=license['team']['id'], name=license['team']['name']))
        return sorted(teams, key=lambda x: x.name)

    def get_all_licenses(self):
        return self.get_licenses(product_code='II', assigned=None)

    def get_all_free_licenses(self):
        return self.get_licenses(product_code='II', assigned=False)

    def get_all_assigned_licenses(self):
        return self.get_licenses(product_code='II', assigned=True)

    def get_licenses(self, product_code: str = 'II', assigned: bool = None):
        """Get all licenses for the customer."""
        free_licenses = []
        page = 1
        while True:
            licenses_resp = self.session.get(
                f"{BASE_URL}/customer/licenses",
                params={
                    'page': page,
                    'productCode': product_code,
                    'perPage': 100,
                    'assigned': assigned
                })
            licenses_resp.raise_for_status()
            licenses_page = licenses_resp.json()
            if not licenses_page:
                break
            free_licenses.extend(licenses_page)
            page += 1
        return free_licenses

    def assign_license(self, email: str, license_code: str):
        """Assign a license to a user."""
        payload = {
            "contact": {
                "email": email,
                "firstName": "",
                "lastName": ""
            },
            "includeOfflineActivationCode": True,
            "license": {
                "productCode": "II",
                "team": 1
            },
            "licenseId": license_code,
            "sendEmail": True}
        assign_resp = self.session.post(
            f"{BASE_URL}/customer/licenses/{license_code}/assign",
            json=payload)
        assign_resp.raise_for_status()
        return assign_resp.json()

    def get_team_licenses(self, team_id: str):
        """Get all licenses for a team."""
        team_licenses = []
        page = 1
        while True:
            licenses_resp = self.session.get(
                f"{BASE_URL}/customer/teams/{team_id}/licenses",
                params={'perPage': 100})
            licenses_resp.raise_for_status()
            licenses_page = licenses_resp.json()
            if not licenses_page:
                break
            team_licenses.extend(licenses_page)
            page += 1
        return team_licenses
