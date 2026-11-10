# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "ruamel.yaml"]
# ///
"""Check whether an Entra ID service principal can look up users through Microsoft Graph.

Run it on the server that holds the real credentials. It never prints a secret or a token; it prints the
application id, the tenant, the permissions ("roles") in the token Graph accepted, and whether user lookups work.

Credentials sources (give one or more):
  --azdo [FILE]                 config/azdo.credentials.yml (keys tenant_id, client_id, client_secret)
  --kubernetes FILE [--env NAME ...]
                                a Kubernetes/OpenShift <config>.credentials.yml: one entry per environment with
                                tenantId, servicePrincipalId and servicePrincipalKey (all environments that
                                have them if no --env is given)

Examples:
  uv run scripts/check_entra_credentials.py --azdo
  uv run scripts/check_entra_credentials.py --kubernetes config/openshift.credentials.yml --email jdoe@example.com

With --email, it also looks that address up the way the bot would (mail, userPrincipalName, otherMails and
proxyAddresses). Graph needs the application permission "User.Read.All" (with admin consent) for that; without it
you get HTTP 403 "Insufficient privileges".
"""
import argparse
import base64
import datetime
import json
import pathlib
import sys

import requests
from ruamel.yaml import YAML

GRAPH_SCOPE = 'https://graph.microsoft.com/.default'
GRAPH_USERS = 'https://graph.microsoft.com/v1.0/users'


def _load(path: pathlib.Path) -> dict:
    with path.open(encoding='utf-8') as f:
        return YAML(typ='safe').load(f) or {}


def _sources(args) -> list[tuple[str, dict]]:
    found = []
    if args.azdo is not None:
        data = _load(pathlib.Path(args.azdo))
        if not {'tenant_id', 'client_id', 'client_secret'} <= data.keys():
            sys.exit(f"{args.azdo}: no tenant_id/client_id/client_secret (is it a PAT setup?)")
        found.append((f"azdo ({args.azdo})", {'tenant': data['tenant_id'], 'id': data['client_id'],
                                               'secret': data['client_secret']}))
    if args.kubernetes:
        for name, creds in _load(pathlib.Path(args.kubernetes)).items():
            if args.env and name not in args.env:
                continue
            if isinstance(creds, dict) and {'tenantId', 'servicePrincipalId', 'servicePrincipalKey'} <= creds.keys():
                found.append((f"{args.kubernetes}:{name}", {'tenant': creds['tenantId'],
                                                           'id': creds['servicePrincipalId'],
                                                           'secret': creds['servicePrincipalKey']}))
    if not found:
        sys.exit("No service principal credentials found (see --help)")
    return found


def _claims(token: str) -> dict:
    payload = token.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))


def _odata_quote(value: str) -> str:
    return value.replace("'", "''")


def _lookup_filter(email: str) -> str:
    e = _odata_quote(email)
    return (f"mail eq '{e}' or userPrincipalName eq '{e}' or otherMails/any(m:m eq '{e}') "
            f"or proxyAddresses/any(p:p eq 'smtp:{e}')")


def check(label: str, creds: dict, email: str | None) -> bool:
    print(f"\n== {label}")
    print(f"   application {creds['id']}, tenant {creds['tenant']}")
    response = requests.post(
        f"https://login.microsoftonline.com/{creds['tenant']}/oauth2/v2.0/token",
        data={'grant_type': 'client_credentials', 'client_id': creds['id'], 'client_secret': creds['secret'],
              'scope': GRAPH_SCOPE}, timeout=30)
    body = response.json()
    if 'access_token' not in body:
        print(f"   TOKEN FAILED: {body.get('error')}: {(body.get('error_description') or '').splitlines()[0]}")
        return False
    claims = _claims(body['access_token'])
    expires = datetime.datetime.fromtimestamp(claims.get('exp', 0), datetime.timezone.utc)
    print(f"   token OK, valid until {expires:%Y-%m-%d %H:%M} UTC")
    roles = claims.get('roles', [])
    print(f"   Graph permissions in the token: {', '.join(sorted(roles)) or '(none)'}")
    if not roles:
        print("   -> no Graph application permission has been granted to this application")

    headers = {'Authorization': f"Bearer {body['access_token']}", 'ConsistencyLevel': 'eventual'}
    probe = requests.get(GRAPH_USERS, headers=headers, params={'$top': 1, '$select': 'id'}, timeout=30)
    if probe.ok:
        print("   list users: OK")
    else:
        error = probe.json().get('error', {})
        print(f"   list users: HTTP {probe.status_code} {error.get('code')}: {error.get('message')}")
        return False

    if email:
        found = requests.get(GRAPH_USERS, headers=headers, timeout=30, params={
            '$filter': _lookup_filter(email), '$count': 'true',
            '$select': 'displayName,userPrincipalName,mail,accountEnabled'})
        if not found.ok:
            error = found.json().get('error', {})
            print(f"   look up {email}: HTTP {found.status_code} {error.get('code')}: {error.get('message')}")
            return False
        users = found.json().get('value', [])
        if not users:
            print(f"   look up {email}: not found")
        for user in users:
            print(f"   look up {email}: {user.get('displayName')} <{user.get('userPrincipalName')}> "
                  f"enabled={user.get('accountEnabled')}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--azdo', nargs='?', const='config/azdo.credentials.yml', metavar='FILE')
    parser.add_argument('--kubernetes', metavar='FILE')
    parser.add_argument('--env', action='append', metavar='NAME', help='only these environments of --kubernetes')
    parser.add_argument('--email', help='also look this address up')
    args = parser.parse_args()

    results = [check(label, creds, args.email) for label, creds in _sources(args)]
    print(f"\n{sum(results)} of {len(results)} credential sets can read users through Microsoft Graph.")
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
