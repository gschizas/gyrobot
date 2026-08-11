"""GitHub provisioning helpers for multi-stage invite/accept/assign workflow.

This module handles checking pending GitHub invitations and auto-assigning users
to teams once their invitations are accepted.
"""
import logging
from typing import List, Dict, Any
from uuid import UUID
import datetime

from backend.account_storage import get_pending_provisions, set_provision_status, get_account
from backend.github_api import GitHubApi

logger = logging.getLogger(__name__)

github_api_client: GitHubApi | None = None

def init_github_client() -> None:
    global github_api_client
    if github_api_client is None:
        github_api_client = GitHubApi()
        logger.info("GitHub API client initialized")


def check_github_invitations() -> Dict[str, Any]:
    """Check pending GitHub invitations and auto-assign accepted users.
    
    Returns a dict with summary of actions taken:
    {
        'total_pending': int,
        'accepted_and_assigned': List[str],  # list of usernames
        'failed': List[{username: str, error: str}],
        'errors': List[str],
    }
    """
    global github_api_client

    results = {
        'total_pending': 0,
        'accepted_and_assigned': [],
        'failed': [],
        'errors': [],
    }
    
    try:
        # Get all pending GitHub invitations
        pending = get_pending_provisions('github', 'invited')
        results['total_pending'] = len(pending)
        
        if not pending:
            logger.debug("No pending GitHub invitations to check")
            return results
        
        logger.info(f"Checking {len(pending)} pending GitHub invitations")
        
        for provision in pending:
            try:
                # Load account metadata
                account = get_account(provision.account_id)
                if not account:
                    results['failed'].append({
                        'username': provision.data.get('username', 'unknown'),
                        'error': 'Account not found',
                    })
                    continue
                
                username = provision.data.get('username')
                team = provision.data.get('team')
                
                if not username or not team:
                    results['failed'].append({
                        'username': username or 'unknown',
                        'error': 'Missing username or team in provision data',
                    })
                    continue

                # Check GitHub invitation status
                init_github_client()
                invitations = github_api_client.get_pending_invitations()
                if username in invitations:
                    logger.debug(f"Invitation for {username} is still pending")
                    continue  # Invitation not yet accepted

                all_users = github_api_client.get_ent_members()
                all_user_logins = {user['login'] for user in all_users}
                if username not in all_user_logins:
                    results['failed'].append({
                        'username': username,
                        'error': 'User not found in GitHub organization',
                    })
                    logger.warning(f"User {username} not found in GitHub organization")
                    continue
                logger.debug(f"Invitation for {username} has been accepted")
                # Assign user to team
                try:
                    github_api_client.add_users_to_ent_team(team, [username])
                    provision.data['accepted_at'] = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
                    provision.data['assigned_at'] = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
                    set_provision_status(provision.account_id, 'github', 'assigned', provision.data)
                    results['accepted_and_assigned'].append(username)
                    logger.info(f"Auto-assigned {username} to GitHub team {team}")
                except Exception as e:
                    logger.exception(f"Failed to assign {username} to team {team}: {e}")
                    results['failed'].append({
                        'username': username,
                        'error': str(e),
                    })
            except Exception as e:
                logger.exception(f"Error checking invitation for {provision.data.get('username', 'unknown')}: {e}")
                results['errors'].append(str(e))

        logger.info(f"GitHub invitation check complete: "
                    f"{len(results['accepted_and_assigned'])} assigned, "
                    f"{len(results['failed'])} failed, "
                    f"{len(results['errors'])} errors")

    except Exception as e:
        logger.exception("Unexpected error during GitHub invitation check")
        results['errors'].append(f"Unexpected error: {str(e)}")

    return results
