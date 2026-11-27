"""Atlassian Crowd provisioning: the user is looked up in Active Directory, created in Crowd (if missing), added
to the requested Crowd groups and emailed a welcome message with the generated password.

The password is only ever held in memory: it is never logged, returned in a result or stored in ``provision_data``.
The groups are the ones the canonical team maps to (``config/team_mapping.yml``, ``crowd:`` section), or the Crowd
group of the same name when there is no mapping, plus ``account.provision_data['extra_groups']``.
"""
import dataclasses
import functools
import secrets

from backend import bot_identity
from backend.accounts import Provision
from backend.bitbucket_api import BitbucketApi
from backend.crowd_api import CrowdApi
from backend.crowd_config import CrowdSettings, load_settings
from backend.email_logging import send_email
from backend.ldap_directory import LdapDirectory, Person
from backend.providers.base import ProvisionRequest
from backend.team_mapping import resolve_teams

EMAIL_SUBJECT = 'Your Atlassian account / Ο λογαριασμός σου στην Atlassian'

# ``onboard move`` passes the full list of mapped groups to ``change_team`` instead of just the first one
RECEIVES_ALL_TEAMS = True


def generate_password() -> str:
    """Two random words and a two-digit number, e.g. ``plenty-wonder-42``."""
    from xkcdpass import xkcd_password as xp
    words = xp.generate_wordlist(wordfile=xp.locate_wordfile(), min_length=5, max_length=8, valid_chars='[a-z]')
    return f"{xp.generate_xkcdpassword(words, numwords=2, delimiter='-')}-{secrets.randbelow(100):02}"


def team_groups_for(team: str, available) -> list[str]:
    """The Crowd groups of ``team``: the ones the canonical team maps to, else the Crowd group of that very name."""
    mapped = resolve_teams('crowd', team)
    if mapped:
        return mapped
    return [team] if team in available else []


def _find_person(settings: CrowdSettings, email: str) -> Person:
    directory = LdapDirectory(settings)
    try:
        person = directory.find_person(email)
    finally:
        directory.close()
    if not person:
        raise RuntimeError(f"{email} was not found in the directory")
    if not (person.mail and person.first_name and person.last_name and person.username):
        raise RuntimeError(f"The directory entry of {email} lacks a mail address or a name")
    return person


@functools.lru_cache(maxsize=1)
def _bitbucket(url: str) -> BitbucketApi:
    """One shared client, so its cache serves consecutive onboardings."""
    return BitbucketApi(url)


def _repositories(ctx, settings: CrowdSettings, api: CrowdApi, groups: list[str]) -> list[dict]:
    """Repositories the groups give access to; empty if Bitbucket is not configured or cannot be reached."""
    if not settings.bitbucket_url or not groups:
        return []
    try:
        parents = {parent for group in groups for parent in api.get_parent_groups(group)}
        return _bitbucket(settings.bitbucket_url).repos_for_groups(groups, inherited_groups=parents)
    except Exception as e:
        ctx.logger.warning(f"Could not list the Bitbucket repositories of {', '.join(groups)}: {e!r}")
        return []


def _send_welcome(settings: CrowdSettings, person: Person, password: str | None, groups: list[str], is_new: bool,
                  repos: list[dict] | None = None):
    welcome = settings.welcome
    send_email(
        'crowd_welcome', to=person.mail, subject=EMAIL_SUBJECT, bot_name=bot_identity.bot_name(),
        username=person.username, password=password, first_name=person.first_name, last_name=person.last_name,
        email=person.mail, is_new=is_new, groups=groups, repos=repos or [], portal_url=welcome.portal_url,
        help_links=list(welcome.help_links), hosts_note=welcome.hosts_note)


def provision(ctx, account: ProvisionRequest, api: CrowdApi | None = None) -> str:
    """Create/enable the Crowd user for ``account.email``.

    Groups are the ones the canonical team ``account.team`` maps to, plus ``account.provision_data['extra_groups']``.
    """
    settings = load_settings()
    extra_groups = list(account.provision_data.get('extra_groups') or [])
    person = _find_person(settings, account.email)
    given_name = (account.provision_data.get('given_name') or '').strip()
    surname = (account.provision_data.get('surname') or '').strip()
    if given_name or surname:
        person = dataclasses.replace(person, first_name=given_name or person.first_name,
                                     last_name=surname or person.last_name)
    api = api or CrowdApi(settings)

    available = api.get_groups()
    team_groups = team_groups_for(account.team, available) if account.team else []
    if account.team and not team_groups:
        raise RuntimeError(f"No Crowd group mapping for team {account.team}")
    groups = list(dict.fromkeys(team_groups + extra_groups))
    unknown = [g for g in groups if g not in available]
    if unknown:
        raise RuntimeError(f"Unknown Crowd group(s): {', '.join(unknown)}")

    password = None
    existing = api.get_user(person.username)
    if existing is None:
        password = generate_password()
        api.create_user(person.username, person.first_name, person.last_name, person.mail, password)
    else:
        if (existing.get('email') or '').lower() != person.mail:
            raise RuntimeError(f"Crowd user {person.username} exists with a different email address "
                               f"({existing.get('email')}), not touching it")
        if not existing.get('active', True):
            api.set_active(person.username, True)
    for group in groups:
        api.add_to_group(person.username, group)

    account.provision_data.update({'username': person.username, 'email': person.mail,
                                   'team_groups': team_groups, 'extra_groups': extra_groups})
    verb = 'Created' if password else 'Updated existing'
    message = f"{verb} Crowd user {person.username}, groups: {', '.join(groups) or '(none)'}"
    repos = _repositories(ctx, settings, api, groups)
    try:
        _send_welcome(settings, person, password, groups, is_new=bool(password), repos=repos)
    except Exception as e:
        ctx.logger.warning(f"Could not send the Crowd welcome email to {person.mail}: {e!r}")
        if password:
            # Nobody knows the password now: the user has to use the password-reset link
            raise RuntimeError(f"{message}, but the welcome email to {person.mail} FAILED ({e}); "
                               f"ask the user to reset the password in Crowd") from e
        return f"{message} (welcome email to {person.mail} FAILED: {e})"
    ctx.logger.info(message)
    return f"{message} (welcome email sent to {person.mail}){_notify_manager(ctx, settings, person, groups, bool(password), repos)}"


def _find_manager(settings: CrowdSettings, person: Person) -> Person | None:
    directory = LdapDirectory(settings)
    try:
        return directory.get_manager(person)
    finally:
        directory.close()


def _notify_manager(ctx, settings: CrowdSettings, person: Person, groups: list[str], is_new: bool,
                    repos: list[dict]) -> str:
    """Tell the person's manager about the account (never the password). Best effort: returns a note for the result."""
    try:
        manager = _find_manager(settings, person)
        if manager is None or not manager.mail:
            return ''
        send_email(
            'crowd_manager_notice', to=manager.mail, subject=f"Crowd account for {person.display_name}",
            username=person.username, first_name=person.first_name, last_name=person.last_name, is_new=is_new,
            groups=groups, repos=repos)
    except Exception as e:
        ctx.logger.warning(f"Could not notify the manager of {person.mail}: {e!r}")
        return f" (notifying the manager FAILED: {e})"
    return f" (manager {manager.mail} notified)"


def deprovision(ctx, provision: Provision, api: CrowdApi | None = None) -> str:
    """Remove the user from all their groups and deactivate them."""
    username = provision.data['username']
    api = api or CrowdApi()
    if api.get_user(username) is None:
        return f"Crowd user {username} no longer exists"
    groups = api.get_user_groups(username)
    for group in groups:
        api.remove_from_group(username, group)
    api.set_active(username, False)
    message = f"Deactivated Crowd user {username}, removed from {len(groups)} group(s)"
    ctx.logger.info(message)
    return message


def change_team(ctx, provision: Provision, new_teams: list[str], api: CrowdApi | None = None) -> str:
    """Swap the groups of the old canonical team for the ones of the new canonical team (extra groups are kept).

    ``new_teams`` is the full list of Crowd groups the new canonical team maps to (see ``RECEIVES_ALL_TEAMS``).
    """
    username = provision.data['username']
    api = api or CrowdApi()
    new_groups = list(new_teams)
    old_groups = list(provision.data.get('team_groups') or [])
    extra = list(provision.data.get('extra_groups') or [])
    available = api.get_groups()
    unknown = [g for g in new_groups if g not in available]
    if unknown:
        raise RuntimeError(f"Unknown Crowd group(s): {', '.join(unknown)}")
    for group in new_groups:
        api.add_to_group(username, group)
    for group in old_groups:
        if group not in new_groups and group not in extra:
            api.remove_from_group(username, group)
    provision.data['team_groups'] = new_groups
    message = f"Moved Crowd user {username} from {', '.join(old_groups) or '(none)'} to {', '.join(new_groups)}"
    ctx.logger.info(message)
    return message