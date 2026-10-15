"""Atlassian Crowd directory provisioning (STUB).

Real integration target: Crowd REST API
    POST   /rest/usermanagement/1/user        (create user)
    DELETE /rest/usermanagement/1/user        (remove user)
"""
from backend.accounts import Provision
from backend.providers.base import ProvisionRequest


def provision(ctx, account: ProvisionRequest) -> str:
    # TODO: create the user in Crowd via the Crowd REST API.
    ctx.logger.info(f"[stub] Create Crowd entry for {account.email}")
    return f"Crowd entry would be created for {account.name} <{account.email}> (stub)"


def deprovision(ctx, account: ProvisionRequest) -> str:
    # TODO: remove the user from Crowd via the Crowd REST API.
    ctx.logger.info(f"[stub] Remove Crowd entry for {account.email}")
    return f"Crowd entry would be removed for {account.name} <{account.email}> (stub)"


def change_team(ctx, provision: Provision, new_team: str) -> str:
    # TODO: move the user between Crowd groups via the Crowd REST API.
    ctx.logger.info(f"[stub] Move Crowd user {provision.data.get('username')} to group {new_team}")
    provision.data['team'] = new_team
    return f"Crowd group of {provision.data.get('username')} would change to {new_team} (stub)"
