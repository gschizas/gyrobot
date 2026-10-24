# Approval queue

Any command decorated with `requires_approval` (today: `onboard ...` and `offboard`) does not run when issued. It is
validated and queued as a **pending request**, and a designated approver must approve it. Approving re-runs the
original command with the stored parameters. Needs `APPROVAL_DATABASE_URL`.

## Life of a request

1. A requester issues the command. The bot checks that they may request it (and in this channel), validates the
   parameters, and replies "Request #N queued for approval".
2. The approvals **notify channel** (always a chat channel, even when the request came from the web UI or API) gets
   "New approval request #N" with the command to approve it, and an email log is sent if configured.
3. An approver runs `approvals approve N`. The command body executes. The result is stored and the requester and the
   notify channel are told. If it fails, the request is marked `failed` with the error.
4. Or an approver runs `approvals reject N`, optionally with a reason.

Requests have the statuses `pending`, `approved`, `executed`, `failed` and `rejected`.

## `approvals` (alias `approval`)

All subcommands are limited to approvers, in the approve channels.

| Command | Description |
|---|---|
| `approvals list` | Pending requests: id, time, requester, command and summary. |
| `approvals show <id>` | Full detail of one request: status, command, parameters, requester, decision and result. |
| `approvals approve <ids...>` | Approves and executes the requests. |
| `approvals reject <ids...> [-r REASON]` | Rejects pending requests. |

`ids` accepts numbers (`90`), ranges (`92-95`), comma-separated combinations (`90,92-95,99-100`), several arguments,
or `all` for every pending request. Requests that are not pending are reported and skipped.

You cannot approve your own request, unless self-approval is switched on in the configuration.

## Who may do what

Permissions come from the `permission_rules` table (see [PERMISSIONS.md](PERMISSIONS.md)):

- the rule of each gated command (for example `commands.onboarding.github:onboard_github`) says who may request it
  and from which channels;
- one shared global rule says who may approve, in which channels, whether self-approval is allowed, and which channel
  is the notify channel.

Users accept `*`, a user id, or `@group` (a group in `data/crowd_users.yml`). Channels use the display name including
the `#` or lock prefix, or `*` for any.

## Writing a gated command

```python
@onboard.command('crowd')
@click.argument('username')
@click.pass_context
@requires_approval(summarize=my_summary, validate=my_validate)
def onboard_crowd(ctx, username):
    ...   # runs only after approval
```

The parameters must be JSON-serialisable. `summarize(params)` returns the one-line description shown to approvers.
`validate(params, ctx)` returns an error text to reject the request before it is queued, and may clean up `params`.
