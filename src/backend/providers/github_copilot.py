"""GitHub Copilot licence provisioning (STUB).

Real integration target: GitHub Copilot seat management API
    POST/DELETE /orgs/{org}/copilot/billing/selected_users
See backend/github_sdk.py for an authenticated requests.Session pattern.
"""
from backend.providers.base import ProvisionRequest
from backend.github_api import GitHubApi

def provision(ctx, account: ProvisionRequest) -> str:
    # TODO: assign a Copilot seat via the GitHub Copilot billing API.
    ctx.logger.info(f"Sending Invitation to {account.userid}")
    invitation = GitHubApi().invite_by_username(account.userid)
    account.provision_data['invitation_id'] = invitation['id']
    account.provision_data['invited_at'] = invitation['createdAt']
    return f"Sent invitation {invitation['id']} at {invitation['createdAt']} to {account.userid}"


def deprovision(ctx, account: ProvisionRequest) -> str:
    # TODO: remove the Copilot seat via the GitHub Copilot billing API.
    ctx.logger.info(f"[stub] Remove {account.userid} from GitHub enterprise")
    return f"Removed {account.userid} from GitHub enterprise (stub)"
