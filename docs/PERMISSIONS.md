# Permissions

Who may run a command, and where, is stored in the PostgreSQL table `permission_rules` (`PERMISSIONS_DATABASE_URL`)
and cached by each process. The schema is managed by Alembic (`uv run alembic -x env=<env-name> upgrade head`).

## Rules

A rule is identified by a **function** (`module:function`, for example `commands.onboarding.github:onboard_github`),
an **environment** (`global` or a named environment such as an OpenShift namespace) and a **role** (`default` unless a
command defines more). A rule holds:

- `users`: who may run it. `*` for everyone, a chat user id, or `@group` (a group in `data/crowd_users.yml`);
- `channels`: where it may be run. `*`, or the display name with its prefix (`#` public, lock icon private);
- `extra`: free-form JSON for rule-specific settings (for example the approval rule's notify channel).

If there is no rule for a command, it is denied.

`$webui` and `$api` are pseudo-channels for the web UI and the REST API.

## Commands

| Command | Description |
|---|---|
| `permissions reload` (aliases `perms refresh`) | Invalidates this bot process's cache so rules are re-read from the database on next use. Use after changing rules in the database or in the web UI (the web UI only refreshes its own process). |
| `permissions show <function> [environment] [role]` | Shows the users, channels and extra settings of one rule. |

Both are themselves permission-checked.

## Changing rules

- **Web UI**: `/admin/permissions` lists, filters, creates, edits and deletes rules, and shows a change history. See
  [WEB-AND-API.md](WEB-AND-API.md).
- **Seeding**: `scripts/migrate_permissions.py --to-db` loads rules from the older YAML files and creates the rule that
  gates the web page (`webapp.routers.permissions:manage`). Set the administrator's user id in the script first.
  Running it again overwrites that rule.
