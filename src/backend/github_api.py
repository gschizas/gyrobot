import pathlib
import time

import jwt
import requests
from bot_framework.yaml_wrapper import yaml

GITHUB_API_URL = "https://api.github.com"
GRAPHQL_URL = f"{GITHUB_API_URL}/graphql"


class GitHubApi():
    enterprise: str
    organization: str
    client_id: str
    client_secret: str
    signing_key: str
    enterprise_id: str | None = None
    _ses_ent: requests.Session | None = None
    _ses_org: requests.Session | None = None
    _ses_inst: requests.Session | None = None
    _ses_usr: requests.Session | None = None
    _jwt_token: str | None = None
    _iat: int | None = None
    _exp: int | None = None

    def _ses_check_expiration(self):
        if self._iat is None or self._exp is None or self._jwt_token is None:
            self._init_sessions()
        if self._exp < int(time.time()):
            self._init_sessions()

    @property
    def ses_ent(self) -> requests.Session:
        self._ses_check_expiration()
        if self._ses_ent is None:
            self._init_sessions()
        assert self._ses_ent is not None
        return self._ses_ent

    @property
    def ses_org(self) -> requests.Session:
        self._ses_check_expiration()
        if self._ses_org is None:
            self._init_sessions()
        assert self._ses_org is not None
        return self._ses_org

    @property
    def ses_inst(self) -> requests.Session:
        self._ses_check_expiration()
        if self._ses_inst is None:
            self._init_sessions()
        assert self._ses_inst is not None
        return self._ses_inst

    @property
    def ses_usr(self) -> requests.Session:
        self._ses_check_expiration()
        if self._ses_usr is None:
            self._init_sessions()
        assert self._ses_usr is not None
        return self._ses_usr

    def _init_sessions(self):
        self._iat = int(time.time())
        self._exp = int(time.time()) + 600

        payload = {
            'iat': self._iat,  # Issued at time
            'exp': self._exp,  # JWT expiration time (10 minutes maximum)
            'iss': self.client_id  # GitHub App's client ID
        }

        # Create JWT
        self._jwt_token = jwt.encode(payload, self.signing_key, algorithm='RS256')
        assert self._jwt_token is not None

        self._ses_inst = requests.session()
        assert self._ses_inst is not None

        self._ses_inst.headers['Accept'] = 'application/vnd.github+json'
        self._ses_inst.headers['Authorization'] = 'Bearer ' + self._jwt_token
        self._ses_inst.headers['X-GitHub-Api-Version'] = '2026-03-10'

        installations_page = self.ses_inst.get(f"{GITHUB_API_URL}/app/installations")
        installations = installations_page.json()
        ent_inst_id = [inst for inst in installations if inst['target_type'] == 'Enterprise'][0]['id']
        org_inst_id = [inst for inst in installations if inst['target_type'] == 'Organization'][0]['id']
        access_tokens_ent = self.ses_inst.post(f"{GITHUB_API_URL}/app/installations/{ent_inst_id}/access_tokens")
        access_tokens_org = self.ses_inst.post(f"{GITHUB_API_URL}/app/installations/{org_inst_id}/access_tokens")

        token_ent = access_tokens_ent.json()['token']
        self._ses_ent = requests.session()
        assert self._ses_ent is not None
        self._ses_ent.headers['Accept'] = 'application/vnd.github+json'
        self._ses_ent.headers['Authorization'] = 'Bearer ' + token_ent
        self._ses_ent.headers['X-GitHub-Api-Version'] = '2026-03-10'

        token_org = access_tokens_org.json()['token']
        self._ses_org = requests.session()
        assert self._ses_org is not None
        self._ses_org.headers['Accept'] = 'application/vnd.github+json'
        self._ses_org.headers['Authorization'] = 'Bearer ' + token_org
        self._ses_org.headers['X-GitHub-Api-Version'] = '2026-03-10'

        self._ses_usr = requests.session()
        assert self._ses_usr is not None
        self._ses_usr.headers['Accept'] = 'application/vnd.github+json'
        self._ses_usr.headers['Authorization'] = 'Bearer ' + self.personal_access_token
        self._ses_usr.headers['X-GitHub-Api-Version'] = '2026-03-10'

    def __init__(self):
        self.enterprise_id = None
        self._load_config()
        self._init_sessions()

    def _load_config(self):
        config_file = pathlib.Path(f'config/github.yml')
        if config_file.exists():
            with config_file.open(mode='r', encoding='utf8') as y:
                config = dict(yaml.load(y))
        self.client_id = config['client_id']
        self.client_secret = config['client_secret']
        self.enterprise = config['enterprise']
        self.organization = config['organization']
        self.signing_key = config['signing_key']
        self.personal_access_token = config['personal_access_token']

    def _github_api_call(self, ses: requests.Session, url: str, **kwargs):
        final_url = url.format(**kwargs)
        results = []
        page = 1

        while True:
            response: requests.Response = ses.get(final_url, params={"per_page": 100, "page": page})
            response.raise_for_status()
            data = response.json()
            if not data:
                break
            results.extend(data)
            if 'link' not in response.headers:  # one page:
                break
            page += 1

        return results

    def get_org_teams(self):
        return self._github_api_call(self.ses_org, f"{GITHUB_API_URL}/orgs/{{org}}/teams", org=self.organization)

    def get_ent_teams(self):
        return self._github_api_call(self.ses_ent, f"{GITHUB_API_URL}/enterprises/{{ent}}/teams", ent=self.enterprise)

    def get_org_team_members(self, team):
        return self._github_api_call(self.ses_org, f"{GITHUB_API_URL}/orgs/{{org}}/teams/{team}/members",
                                     org=self.organization, team=team)

    def get_ent_team_members(self, team):
        return self._github_api_call(self.ses_ent, f"{GITHUB_API_URL}/enterprises/{{ent}}/teams/{{team}}/memberships",
                                     ent=self.enterprise, team=team)

    def get_org_invitations(self):
        return self._github_api_call(f"{GITHUB_API_URL}/orgs/{{org}}/invitations", org=self.organization)

    def get_org_members(self):
        return self._github_api_call(self.ses_org, f"{GITHUB_API_URL}/orgs/{{self.organization}}/members")

    def get_ent_members(self):
        QUERY = """
        query ListEnterpriseMembersWithEmail($entLogin: String!, $orgLogin: String!, $cursor: String) {
          enterprise(slug: $entLogin) {
            members(first: 100, after: $cursor) {
              nodes {
                ... on EnterpriseUserAccount {
                  login
                  name
                  user {
                    organizationVerifiedDomainEmails(login: $orgLogin)
                    createdAt
                    organizations(first: 100) {
                      nodes {
                        login
                      }
                    }            
                  }
                }
              }
              pageInfo {
                hasNextPage
                endCursor
              }
              totalCount
            }
          }
        }
        """
        cursor = None
        all_members = []

        while True:
            response = self.ses_usr.post(
                GRAPHQL_URL,
                json={"query": QUERY,
                      "variables": {"entLogin": self.enterprise, "orgLogin": self.organization, "cursor": cursor}},
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                raise RuntimeError(f"GraphQL errors: {data['errors']}")

            members_data = data["data"]["enterprise"]["members"]
            all_members.extend(members_data["nodes"])

            if not members_data["pageInfo"]["hasNextPage"]:
                break
            cursor = members_data["pageInfo"]["endCursor"]

        return all_members

    def get_user_details(self, username):
        resp = requests.get(f"{GITHUB_API_URL}/users/{username}")
        resp.raise_for_status()
        return self.ses_ent.get(f"{GITHUB_API_URL}/users/{username}").json()

    def get_sso_identity(self, username):
        url = f"{GITHUB_API_URL}/orgs/{self.organization}/memberships/{username}"
        response = self.ses_org.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get("user", {}).get("login"), data.get("user", {}).get("sso", {}).get("login")
        return username, None

    def get_pending_invitations(self):
        QUERY = """
        query ListPendingUnaffiliatedInvitations($slug: String!, $cursor: String) {
          enterprise(slug: $slug) {
            ownerInfo {
              pendingUnaffiliatedMemberInvitations(first: 100, after: $cursor) {
                nodes {
                  id
                  createdAt
                  email
                  invitee { login }
                  inviter { login }
                }
                pageInfo {
                  hasNextPage
                  endCursor
                }
                totalCount
              }
            }
          }
        }
        """
        cursor = None

        response = self.ses_usr.post(
            GRAPHQL_URL,
            json={
                "query": QUERY,
                "variables": {
                    "slug": self.enterprise,
                    "cursor": cursor
                }
            },
        )

        return [inv['invitee']['login'] for inv in
                response.json()['data']['enterprise']['ownerInfo']['pendingUnaffiliatedMemberInvitations']['nodes']]

    # Step 1: Get all org logins in the enterprise
    # Step 2: Get all members with verified domain emails for each org login
    # organizationVerifiedDomainEmails is called once per org inline via an alias
    def build_member_query(self, org_logins: list[str]) -> str:
        email_fragments = "\n".join(
            f'org_{i}: organizationVerifiedDomainEmails(login: "{login}")'
            for i, login in enumerate(org_logins)
        )
        return f"""
            query ListEnterpriseMembers($slug: String!, $cursor: String) {{
              enterprise(slug: $slug) {{
                members(first: 100, after: $cursor) {{
                  nodes {{
                    ... on EnterpriseUserAccount {{
                      login
                      name
                      user {{
                        {email_fragments}
                      }}
                    }}
                    ... on User {{
                      login
                      name
                      {email_fragments}
                    }}
                  }}
                  pageInfo {{ hasNextPage endCursor }}
                  totalCount
                }}
              }}
            }}
            """

    def get_org_logins(self) -> list[str]:
        ORG_QUERY = """
        query GetEnterpriseOrgs($slug: String!, $cursor: String) {
          enterprise(slug: $slug) {
            organizations(first: 100, after: $cursor) {
              nodes { login }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
        """
        cursor = None
        logins = []
        while True:
            response = self.ses_ent.post(
                GRAPHQL_URL,
                json={"query": ORG_QUERY, "variables": {"slug": self.enterprise, "cursor": cursor}},
            )
            response.raise_for_status()
            data = response.json()
            if "errors" in data:
                raise RuntimeError(f"GraphQL errors: {data['errors']}")
            orgs = data["data"]["enterprise"]["organizations"]
            logins.extend(o["login"] for o in orgs["nodes"])
            if not orgs["pageInfo"]["hasNextPage"]:
                break
            cursor = orgs["pageInfo"]["endCursor"]
        return logins

    def extract_verified_emails(self, node: dict, num_orgs: int) -> list[str]:
        """Collect and deduplicate verified domain emails across all org aliases."""
        all_emails = []
        for i in range(num_orgs):
            all_emails.extend(node.get(f"org_{i}") or [])
        return list(dict.fromkeys(all_emails))  # deduplicate, preserve order

    def list_enterprise_members(self) -> list[dict]:
        org_logins = self.get_org_logins()
        if not org_logins:
            raise RuntimeError("No organizations found in enterprise.")

        query = self.build_member_query(org_logins)
        cursor = None
        all_members = []

        while True:
            response = self.ses_ent.post(
                GRAPHQL_URL,
                json={"query": query, "variables": {"slug": self.enterprise, "cursor": cursor}},
            )
            response.raise_for_status()
            data = response.json()
            if "errors" in data:
                raise RuntimeError(f"GraphQL errors: {data['errors']}")

            members_data = data["data"]["enterprise"]["members"]
            for node in members_data["nodes"]:
                # For EnterpriseUserAccount, emails are on the nested user object
                email_source = (node.get("user") or node)
                verified_emails = self.extract_verified_emails(email_source, len(org_logins))
                all_members.append({
                    "login": node["login"],
                    "name": node.get("name") or "",
                    "verified_emails": verified_emails,
                })

            if not members_data["pageInfo"]["hasNextPage"]:
                break
            cursor = members_data["pageInfo"]["endCursor"]

        return all_members

    def add_users_to_ent_team(self, team_name: str, usernames: list[str]) -> list[dict]:
        result = self.ses_ent.post(
            f"https://api.github.com/enterprises/{self.enterprise}/teams/{team_name}/memberships/add",
            json={'usernames': usernames}
        )
        return result.json()

    def fill_enterprise_id(self) -> None:
        get_enterprise_id_query = """
        query GetEnterpriseId($slug: String!) {
          enterprise(slug: $slug) {
            id
          }
        }
        """

        response = self.ses_ent.post(
            GRAPHQL_URL,
            json={"query": get_enterprise_id_query, "variables": {"slug": self.enterprise}},
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        self.enterprise_id = data["data"]["enterprise"]["id"]

    def _run_invite_mutation(self, input_fields: dict) -> dict:
        invite_mutation = """
        mutation InviteEnterpriseMember($input: InviteEnterpriseMemberInput!) {
          inviteEnterpriseMember(input: $input) {
            clientMutationId
            invitation {
              id
              createdAt
              email
              invitee { login }
              inviter { login }
            }
          }
        }
        """

        input_fields["enterpriseId"] = self.enterprise_id
        response = self.ses_ent.post(
            GRAPHQL_URL,
            json={"query": invite_mutation, "variables": {"input": input_fields}},
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data["data"]["inviteEnterpriseMember"]["invitation"]

    def invite_by_username(self, username: str) -> dict:
        if self.enterprise_id is None:
            self.fill_enterprise_id()
        return self._run_invite_mutation({"invitee": username})

    def invite_by_email(self, email: str) -> dict:
        if self.enterprise_id is None:
            self.fill_enterprise_id()
        return self._run_invite_mutation({"email": email})
