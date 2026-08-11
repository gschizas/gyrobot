import json
import os
import time

import numpy as np
import pandas as pd

import jwt
import requests
from requests.structures import CaseInsensitiveDict
from tabulate import tabulate

GITHUB_API_URL = "https://api.github.com"
GRAPHQL_URL = f"{GITHUB_API_URL}/graphql"

os.environ['HTTP_PROXY'] = 'http://localhost:18899'
os.environ['HTTPS_PROXY'] = 'http://localhost:18899'
os.environ['REQUESTS_CA_BUNDLE'] = f'{os.environ["ONEDRIVECONSUMER"]}/Config/Fiddler/FiddlerRoot-{os.environ["COMPUTERNAME"]}.pem'

class GitHubApi():
    enterprise = 'MY_ENTERPRISE'
    organization = 'MY_ORGANIZATION'

    CLIENT_ID = 'my_client_id'
    CLIENT_SECRET = 'my_client_secret'

    signing_key = """\
    -----BEGIN RSA PRIVATE KEY-----
    REDACTED
    -----END RSA PRIVATE KEY-----
    """

    def init(self):
        payload = {
            # Issued at time
            'iat': int(time.time()),
            # JWT expiration time (10 minutes maximum)
            'exp': int(time.time()) + 600,
            
            # GitHub App's client ID
            'iss': self.CLIENT_ID
        
        }
        
        # Create JWT
        encoded_jwt = jwt.encode(payload, self.signing_key, algorithm='RS256')
        
        self.ses_installation = requests.session()
        
        self.ses_installation.headers['Accept'] = 'application/vnd.github+json'
        self.ses_installation.headers['Authorization'] = 'Bearer ' + encoded_jwt
        self.ses_installation.headers['X-GitHub-Api-Version'] = '2026-03-10'
        
        installations_page = self.ses_installation.get(f"{GITHUB_API_URL}/app/installations")
        
        ent_installation_id = [inst for inst in installations_page.json() if inst['target_type'] == 'Enterprise'][0]['id']
        org_installation_id = [inst for inst in installations_page.json() if inst['target_type'] == 'Organization'][0]['id']
        access_tokens_ent = self.ses_installation.post(f"{GITHUB_API_URL}/app/installations/{ent_installation_id}/access_tokens")
        access_tokens_org = self.ses_installation.post(f"{GITHUB_API_URL}/app/installations/{org_installation_id}/access_tokens")
        
        token_ent = access_tokens_ent.json()['token']
        self.ses_ent = requests.session()
        self.ses_ent.headers['Accept'] = 'application/vnd.github+json'
        self.ses_ent.headers['Authorization'] = 'Bearer ' + token_ent
        self.ses_ent.headers['X-GitHub-Api-Version'] = '2026-03-10'
        
        token_org = access_tokens_org.json()['token']
        self.ses_org = requests.session()
        self.ses_org.headers['Accept'] = 'application/vnd.github+json'
        self.ses_org.headers['Authorization'] = 'Bearer ' + token_org
        self.ses_org.headers['X-GitHub-Api-Version'] = '2026-03-10'

        self.ses_usr = requests.session()
        self.ses_usr.headers['Accept'] = 'application/vnd.github+json'
        # self.ses_usr.headers['Authorization'] = 'Bearer '
        self.ses_usr.headers['X-GitHub-Api-Version'] = '2026-03-10'
 
    def github_api(self, ses: requests.Session, url: str, **kwargs):
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
            if 'link' not in response.headers: # one page:
                break
            page += 1
    
        return results
    
    def get_org_teams(self):
        return self.github_api(self.ses_org, f"{GITHUB_API_URL}/orgs/{{org}}/teams", org=self.organization)
    
    def get_ent_teams(self):
        return self.github_api(self.ses_ent, f"{GITHUB_API_URL}/enterprises/{{ent}}/teams", ent=self.enterprise)
    
    def get_org_team_members(self, team):
        return self.github_api(self.ses_org, f"{GITHUB_API_URL}/orgs/{{org}}/teams/{team}/members", org=self.organization, team=team)
    
    def get_ent_team_members(self, team):
        return self.github_api(self.ses_ent, f"{GITHUB_API_URL}/enterprises/{{ent}}/teams/{{team}}/memberships", ent=self.enterprise, team=team)

    def get_org_invitations(self):
        return self.github_api(f"{GITHUB_API_URL}/orgs/{{org}}/invitations", org=self.organization)

    def get_org_members(self):
        return self.github_api(self.ses_org, f"{GITHUB_API_URL}/orgs/{{self.organization}}/members")

    def get_user_details(self, username):
        return self.ses_ent.get(f"{GITHUB_API_URL}/users/{username}")

    def get_sso_identity(username):
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

        return [inv['invitee']['login'] for inv in response.json()['data']['enterprise']['ownerInfo']['pendingUnaffiliatedMemberInvitations']['nodes']]

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
            response = self.ses_usr.post(
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
            response = self.ses_usr.post(
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