# Azure DevOps reporting

`onboard azdo` (aliases `onboard devops`, `onboard azuredevops`) reports how many users each canonical team has in Azure DevOps and at which
**access level** (the level is what costs money). There is nothing to onboard or offboard: users arrive through
Entra ID, which is synchronised with Active Directory, and leave the same way.

The bot reads the user entitlements of the organisation, matches each user to an account by email (the primary
email or one of `additional_emails`) and takes the canonical team from the account. Everything is read-only
except `onboard azdo link`.

## Commands

| Command | Description |
|---|---|
| `onboard azdo report [-x]` | One row per canonical team: users per access level, total and (with prices configured) cost per month, plus a TOTAL row. Users matching no account are counted under `unknown` and listed in a second table; accounts without a team are under `(no team)`. |
| `onboard azdo users [team] [-x]` | The users of the canonical teams starting with `team` (all if omitted; `unknown` for unmatched users): email, name, team, access level, licensing source, status and last access date. |
| `onboard azdo whois <email>` | One user's details and how their access level changed over time. The email may be the Azure DevOps one or any email of the person's account. |
| `onboard azdo link <azdo email> <account email>` | Attach an unmatched Azure DevOps user to a person as an additional email. Approval-gated; validation checks the Azure DevOps user exists and the address belongs to no account yet. |
| `onboard ado` | Not Azure DevOps. Try it. |

Reading takes a few seconds (100 users per request); the result is reused for five minutes.

## The snapshot

Every read also records each matched person's access level as an `azdo` provision of their account: `active`
while they are in Azure DevOps, `deprovisioned` once they are gone. Only changes are written, so the provision
history (`onboard whois`, `onboard azdo whois`) shows when an access level changed. `offboard` knows the resource and
reports that there is nothing to do; the next read sets it back to `active` if the person is still in Azure DevOps.
`last_accessed` is kept in the data but a change in it alone is not recorded.

## Configuration

`config/azdo.yml` (the commands are only loaded when it exists):

```yaml
organization: <organisation>      # dev.azure.com/<organisation>
auth: pat                         # "pat" (default) or "entra"
costs:                            # optional: price per user per month, by access level name
  Basic: 6
  Stakeholder: 0
  Basic + Test Plans: 52
```

Access level names are the ones `onboard azdo report` prints. A level with no price counts as 0 and is listed under the report.

`config/azdo.credentials.yml` (keep it out of git):

```yaml
pat: <personal access token>      # auth: pat
# auth: entra
tenant_id: <tenant>
client_id: <application id>
client_secret: <secret>
```

### Personal access token

1. In Azure DevOps open *User settings > Personal access tokens > New token*.
2. Organisation: the one in `organization`. Scope: *Custom defined* > **Member Entitlement Management: Read**.
3. The token acts as its owner, who must be allowed to see *Organization settings > Users* (for example a
   Project Collection Administrator). A token expires (at most a year), so note the date; an expired or wrong
   token shows as "Azure DevOps rejected the credentials".

### Entra service principal

Better for a service, since it does not belong to a person and does not expire with a personal token.

1. In Entra ID create an app registration and a client secret; note the tenant, client and secret.
2. In Azure DevOps open *Organization settings > Users*, add the service principal (by its application name) and
   give it access that lets it read the users list (see Microsoft's documentation on service principals and
   managed identities in Azure DevOps for the current steps).
3. Set `auth: entra`. The bot asks Entra for a token with the Azure DevOps scope
   (`499b84ac-1321-427f-aa17-267ca6975798/.default`) and refreshes it itself.

## Permissions

Rules are keyed on the module path, so each command needs one:

- `commands.onboarding.azdo:azdo_report`, `azdo_users`, `azdo_whois`
- `commands.onboarding.azdo:azdo_link` (requester and approver rules, like the other approval-gated commands)
- `commands.onboarding.azdo:ado` (the joke)

## Notes

- Reading **writes** snapshots, so the bot needs `APPROVAL_DATABASE_URL`; without it the module fails to load.
- If Azure DevOps returns no users at all, nobody is marked `deprovisioned` (an empty answer is more likely
  a problem than everybody leaving).
- Two Azure DevOps users matching the same account are both reported, but only the first is stored.
