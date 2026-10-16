"""GitHub Copilot licence provisioning (STUB).

Real integration target: GitHub Copilot seat management API
    POST/DELETE /orgs/{org}/copilot/billing/selected_users
See backend/github_sdk.py for an authenticated requests.Session pattern.
"""
from backend.accounts import Provision
from backend.providers.base import ProvisionRequest
from backend.github_api import GitHubApi

def provision(ctx, account: ProvisionRequest) -> str:
    # TODO: assign a Copilot seat via the GitHub Copilot billing API.
    ctx.logger.info(f"Sending Invitation to {account.userid}")
    invitation = GitHubApi().invite_by_username(account.userid)
    account.provision_data['invitation_id'] = invitation['id']
    account.provision_data['invited_at'] = invitation['createdAt']
    return f"Sent invitation {invitation['id']} at {invitation['createdAt']} to {account.userid}"


def deprovision(ctx, provision: Provision) -> str:
    # TODO: remove the Copilot seat via the GitHub Copilot billing API.
    username = provision.data.get('username', '?')
    ctx.logger.info(f"[stub] Remove {username} from GitHub enterprise")
    return f"Removed {username} from GitHub enterprise (stub)"


def change_team(ctx, provision: Provision, new_team: str) -> str:
    """Move the user to ``new_team`` (an enterprise team slug); updates ``provision.data['team']``."""
    username = provision.data['username']
    old_team = provision.data.get('team')
    if old_team and old_team.lower().removeprefix('ent:') == new_team.lower().removeprefix('ent:'):
        return f"{username} is already in {new_team}"

    if provision.status != 'invited':
        # Add first, so a failure never leaves the user without a team
        api = GitHubApi()
        added = api.add_users_to_ent_team(new_team, [username])
        if isinstance(added, dict) and added.get('message'):
            raise RuntimeError(f"Could not add {username} to {new_team}: {added['message']}")
        if old_team:
            api.remove_users_from_ent_team(old_team, [username])
        message = f"Moved {username} from {old_team or '(none)'} to {new_team}"
    else:
        # Not a member yet: the invitation check will assign the stored team once accepted
        message = f"{username} has a pending invitation; will join {new_team} when accepted"
    provision.data['team'] = new_team
    ctx.logger.info(message)
    return message
