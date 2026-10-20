"""JetBrains IntelliJ IDEA licence provisioning via the JetBrains Account API.

A licence belongs to a JetBrains *team* (a pool of seats). Provisioning takes a free seat of the team,
deprovisioning revokes the user's licences (JetBrains refuses while a licence is under 30 days old).
"""
from backend.accounts import Provision
from backend.jetbrains_api import JetBrainsApi
from backend.providers.base import ProvisionRequest


def provision(ctx, account: ProvisionRequest) -> str:
    """Assign a free licence of the JetBrains team ``account.team`` (a name, id or slug) to ``account.email``."""
    api = JetBrainsApi()
    team = api.find_team(account.team)
    # First/last name are required by the API; a directory lookup can fill them in later
    license_id = api.assign_license(account.email, team.id)
    account.provision_data.update({'license_id': license_id, 'team_id': team.id, 'team_name': team.name})
    ctx.logger.info(f"Assigned JetBrains licence {license_id} of team {team.name} to {account.email}")
    return f"Assigned licence {license_id} of team {team.name} to {account.email}"


def deprovision(ctx, provision: Provision) -> str:
    """Revoke every IntelliJ IDEA licence assigned to the user."""
    email = provision.data['email']
    api = JetBrainsApi()
    if not api.get_assigned_licenses(email):
        return f"{email} has no JetBrains licence assigned (already revoked)"
    revoked = api.revoke_licenses(email)
    message = f"Revoked JetBrains licence {', '.join(revoked) or '(none reported)'} of {email}"
    ctx.logger.info(message)
    return message


def change_team(ctx, provision: Provision, new_team: str) -> str:
    """Transfer the user's licence(s) to the JetBrains team ``new_team``; updates ``provision.data``."""
    email = provision.data['email']
    api = JetBrainsApi()
    target = api.find_team(new_team)
    licenses = api.get_assigned_licenses(email)
    if not licenses:
        raise RuntimeError(f"{email} has no JetBrains licence assigned")
    to_move = [lic for lic in licenses if lic['team']['id'] != target.id]
    if not to_move:
        provision.data.update({'team_id': target.id, 'team_name': target.name})
        return f"{email} is already in JetBrains team {target.name}"

    not_transferable = [lic['licenseId'] for lic in to_move if not lic.get('isTransferableBetweenTeams', True)]
    if not_transferable:
        raise RuntimeError(f"Licence {', '.join(not_transferable)} cannot be transferred between teams")
    api.change_licenses_team([lic['licenseId'] for lic in to_move], target.id)

    # The API silently leaves licences it cannot transfer, so check
    moved_ids = {lic['licenseId'] for lic in api.get_assigned_licenses(email) if lic['team']['id'] == target.id}
    stuck = [lic['licenseId'] for lic in to_move if lic['licenseId'] not in moved_ids]
    if stuck:
        raise RuntimeError(f"JetBrains did not transfer licence {', '.join(stuck)} to {target.name}")
    provision.data.update({'team_id': target.id, 'team_name': target.name})
    message = f"Moved the JetBrains licence of {email} to team {target.name}"
    ctx.logger.info(message)
    return message
