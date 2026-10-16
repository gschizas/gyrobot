"""JetBrains IntelliJ IDEA licence provisioning (STUB).

Real integration target: JetBrains Account / Licenses API for organizations
    https://account.jetbrains.com/ (assign/revoke a subscription seat).
"""
from backend.accounts import Provision
from backend.jetbrains_api import JetBrainsApi
from backend.providers.base import ProvisionRequest


def provision(ctx, account: ProvisionRequest) -> str:
    # TODO: assign a JetBrains IntelliJ IDEA licence seat via the JetBrains API.
    JetBrainsApi().assign_license(account.email)
    ctx.logger.info(f"[stub] Assign JetBrains IntelliJ IDEA licence to {account.email}")
    return f"JetBrains IntelliJ IDEA licence would be assigned to {account.email} (stub)"


def deprovision(ctx, provision: Provision) -> str:
    # TODO: remove the JetBrains IntelliJ IDEA licence seat via the JetBrains API.
    email = provision.data.get('email', '?')
    ctx.logger.info(f"[stub] Remove JetBrains IntelliJ IDEA licence from {email}")
    return f"JetBrains IntelliJ IDEA licence would be removed from {email} (stub)"


def change_team(ctx, provision: Provision, new_team: str) -> str:
    # TODO: move the licence holder to another team via the JetBrains API.
    ctx.logger.info(f"[stub] Move {provision.data.get('email')} to JetBrains team {new_team}")
    provision.data['team_name'] = new_team
    return f"JetBrains team of {provision.data.get('email')} would change to {new_team} (stub)"
