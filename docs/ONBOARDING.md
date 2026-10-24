# Onboarding and offboarding

Needs `APPROVAL_DATABASE_URL`. Requests are stored in PostgreSQL (accounts, provisions, approval queue).

**Every `onboard`/`offboard` command is gated by the [approval queue](APPROVALS.md).** Issuing one checks that you
are allowed to request it, validates it, and queues a pending request. Nothing is provisioned until an approver runs
`approvals approve`. The commands below describe what happens on approval. The same functions are available from the
web UI and REST API, see [WEB-AND-API.md](WEB-AND-API.md).

Core concepts:

- **Account**: one person, identified by their primary email, with a core team (the GitHub enterprise team slug,
  without `ent:`). An account may carry extra addresses (`additional_emails`).
- **Provision**: one resource held by an account (`github`, `jetbrains`, `crowd`, `slack`) with a status such as
  `invited`, `active`, `assigned`, `expired`, `cancelled` or `deprovisioned`.
- **Team mapping** (`config/team_mapping.yml`): maps a core team to each resource's own team. A mapping also covers the
  sub-teams under it, and several core teams may point at one JetBrains team.
- **Allowed email domains** (`allowed_email_domains` in `config/github.yml`): the domains accepted for onboarding.
  Comparison ignores case. Empty means no restriction.

## `onboard`

| Command | Description |
|---|---|
| `onboard github [add] <username> <email> <team>` | Invites the GitHub user to the enterprise and records the invitation. `add` is optional. Validation checks that the GitHub user exists, is not already onboarded (also under an earlier username), that the team exists and that the email domain is allowed. The invitee also gets an email with the direct acceptance link. Once the invitation is accepted, the user is added to the team automatically (see `check`). |
| `onboard github check` | Checks the pending GitHub invitations: users who accepted are assigned to their team, expired invitations are marked. Not gated by approval. It also runs on a schedule. Old name: `onboard github_check`. |
| `onboard github cancel <login\|email\|invitation_id>` | Withdraws a pending invitation and marks the provision `cancelled`. Old name: `onboard github_cancel`. |
| `onboard github expired [team_prefix] [-x]` | Invitations that expired unaccepted, with invitation and expiry times (from the database, since GitHub no longer has them). Not gated by approval. |
| `onboard jetbrains <email> <team_name>` | Assigns a free IntelliJ IDEA licence to the email. `team_name` is a core team (resolved through the team mapping) or a JetBrains team name, slug or id. Validation checks that the team has a free licence and that the person does not already hold one. |
| `onboard crowd <username> <team>` | Queues a Crowd entry. The provider is still a stub. |
| `onboard slack <email> <member_id...>` | Records Slack workspace membership for the email and member ids. The provider is still a stub. |
| `onboard move <email> <team>` | Moves a person to another core team on every resource they hold, using the team mapping for each resource. The account's team is updated only if every resource succeeded, so a failed move can simply be run again. |

## `offboard <email>`

Removes everything the account holds and deactivates Slack:

- every live provision is deprovisioned through its provider (GitHub removal, JetBrains licence revoke, Crowd entry);
- Slack is always attempted, using every email and member id known for the person;
- only resources removed successfully are marked `deprovisioned`. A failure stays live, so the command can be re-run
  after fixing the cause. JetBrains refuses to revoke a licence in the first 30 days after it was assigned, so that
  case is reported as failed.

The command looks the account up by its primary email.

## `github` (read-only)

Needs `GITHUB_TOKEN` and `GITHUB_ORG`. Not gated by approval.

| Command | Description |
|---|---|
| `github teams` | The enterprise team hierarchy as a tree. |
| `github members <team_slug> [-x]` | Members (login, email, team) of every enterprise team whose slug starts with `team_slug`. A missing GitHub email falls back to the one recorded when the bot onboarded the person. With `-x`, Excel with `team L2`/`team L3` columns. |
| `github pending-invitations [team_prefix] [-x]` | Pending invitations, with email and team when the bot sent them. |

## `jetbrains` (read-only)

Needs `JETBRAINS_TOKEN` and `JETBRAINS_CUSTOMER_CODE`. There are no invitations in JetBrains: a licence is assigned
directly.

| Command | Description |
|---|---|
| `jetbrains teams` | The teams the token manages: id, name and slug. The slug is our own convention (the name before `(`, lower case, spaces as dashes), since JetBrains has only an id and a name. |
| `jetbrains members [team] [-x]` | The licences of a team (name, slug or id), or of all teams, with status (`free`, `assigned`, `suspended`), holder, licence id and expiry. |

## Maintenance scripts

Run from the repository root with `uv run python scripts/<name>.py <env-name>`. They preview by default.

| Script | Description |
|---|---|
| `backfill_jetbrains.py` | Records existing JetBrains licences as `active` provisions. `--apply` writes. `--map CSV` links licences held by outside-domain emails to accounts. `--write-email-map FILE` and `--write-team-map FILE` write blank templates to fill in. `--report-misplaced CSV` lists people whose core team maps to a different JetBrains team than the one they hold. |
| `backfill_github_ids.py` | Fills in the GitHub user ids of existing GitHub provisions. |
| `migrate_permissions.py` | Seeds `permission_rules` from the old YAML files (`--to-db`). |
