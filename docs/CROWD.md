# Crowd onboarding

`onboard crowd` creates (or re-enables) a user in Atlassian Crowd, puts them in the groups of their canonical team and
emails them a bilingual welcome message with a generated password and the repositories they can reach.

## Commands

| Command | Description |
|---|---|
| `onboard crowd [add] <login-or-email> <team> [-g group]... [--given-name N] [--surname N]` | Approval-gated. Looks the person up in Active Directory, creates the Crowd user, adds the groups the canonical `team` maps to (plus every `--group`) and sends the welcome email. The name comes from AD (Title Case); the name options override it, and it becomes the account name. |
| `onboard crowd lookup <login-or-email>` | What AD and Crowd know about the person: names, email, Crowd user name, active state, groups. Not gated. |
| `onboard crowd groups [text]` | The assignable groups with descriptions, optionally filtered. Not gated. |
| `onboard crowd teams [text] [-d N] [-f]` | The groups as a tree (only those whose name has `text`, with their parents; `-d` limits the levels; `-f` lists the names flat). A group inside several groups is listed under each, but expanded only once: later copies are marked `(*)`. Not gated. |
| `offboard <email>` | Removes the user from every group and deactivates them (Crowd has no safe delete). |
| `onboard move <email> <team>` | Adds the groups of the new canonical team and removes the ones of the old team (extra groups are kept). |

Validation (before the request is queued): exactly one AD person with an email and names, the team has a `crowd:`
mapping, all groups exist, and the person has no live Crowd provision. The request shows the resolved email.

If the Crowd user already exists the bot only adds the groups (and re-enables an inactive user); it does not send a
new password, and it refuses when the email in Crowd differs from the one in AD.
The password is generated in memory, emailed and never logged, returned or stored. If that email fails the command
reports it so the user can use the password-reset link.

## Configuration

`config/crowd.yml` (gitignored; see the docstring of `backend/crowd_config.py`):

```yaml
crowd_url: https://crowd.example.com/crowd
bitbucket_url: https://bitbucket.example.com    # optional: repositories listed in the email
group_prefixes: [team-, ext-]                   # which groups can be assigned
ldap:
  server: ldap://ad.example.com
  search_base: DC=example,DC=com
  mail_domain: example.com
  authentication: NTLM
  username_attribute: samaccountname            # or: name (the CN)
  greek_name_attribute: extensionAttribute10    # Greek name as GIVEN|SURNAME, upper case (empty: none)
  greek_name_separator: "|"
welcome:
  portal_url: https://crowd.example.com/crowd/
  hosts_note: ...
  help_links:
    - {title: Common git push errors, url: https://wiki.example.com/push-errors}
```

`config/team_mapping.yml`, section `crowd:`, maps a canonical team to one group or a list of groups:

```yaml
crowd:
  payments: [team-payments, team-payments-dev]
```

A team without an entry may also be the name of a Crowd group, which is then used as it is (the web pages pick it
from a tree of the Crowd groups; a group inside several groups appears under each). To seed the section, run
`uv run scripts/suggest_crowd_mapping.py <env-name>`: it fuzzy-matches the canonical teams with the Crowd groups and
writes a suggestion file to edit by hand. `onboard move` resolves teams through the mapping only.

To record the users that already exist in Crowd, run `uv run scripts/import_crowd_users.py <env-name>` (a preview;
add `--apply` to write). It imports the active users inside the mail domain as `crowd` provisions, creating the
missing accounts named from the directory, and keeps their current groups as extra groups so `onboard move` never
removes them., see `SECRET-STORE.md` and `PASS-SETUP.md`):

| Secret | Used for |
|---|---|
| `CROWD_USERNAME`, `CROWD_PASSWORD` | The Crowd application. Only the `usermanagement` API is used: the `admin` API refuses application credentials. |
| `LDAP_BIND_USERNAME`, `LDAP_BIND_PASSWORD` | Read-only AD account. |
| `BITBUCKET_TOKEN` (or `BITBUCKET_USERNAME` + `BITBUCKET_PASSWORD`) | Listing the repositories. Bitbucket refuses the Crowd application credential. Listing permissions needs **Project admin and Repository admin** on the token (only `GET` is used); prefer a service account. |

The email is sent through the bot's usual SMTP settings (`config/email.yml`). The repositories are cached for six
hours, and a Bitbucket failure only leaves them out of the email.

## Development against production

Read-only calls are safe. With the Windows Credential Manager (`config/secrets.dev.yml` with a `keyring` backend),
a corporate proxy and its CA:

```powershell
$env:SECRETS_CONFIGURATION = 'secrets.dev.yml'
$env:CROWD_USERNAME = 'python'
$env:HTTPS_PROXY = 'http://localhost:18899'
$env:REQUESTS_CA_BUNDLE = 'C:\path\to\proxy-root-ca.pem'
```

Store the secrets with `uv run --no-project --with keyring python -m keyring set gyrobot CROWD_PASSWORD`.
`scripts/check_crowd_usernames.py <env>` compares the Crowd users with AD (CN versus `sAMAccountName`) to decide
`ldap.username_attribute`.
