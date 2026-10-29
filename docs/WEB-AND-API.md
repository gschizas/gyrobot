# Web UI and REST API

A FastAPI application with two interfaces over the same commands the chat bot uses. Both drive the real `onboard`
and `offboard` commands, so they go through the same validation, [approval queue](APPROVALS.md) and
[permission rules](PERMISSIONS.md) as chat. Requests are approved in chat. The "new approval request" announcement is
posted to the notify channel in chat, not shown in the web page.

Run with `python src/run_webapp.py <env-name>` (reads `.env.d/<env-name>.env`) or point an ASGI server at
`webapp.main:app`, from the repository root.

| Variable | Purpose |
|---|---|
| `WEBAPP_SESSION_SECRET` | Signs the web session cookie. |
| `WEBAPP_JWT_SECRET` | Signs REST API access tokens. |
| `LDAP_SERVER_URL`, `LDAP_BIND_DN_TEMPLATE` | LDAP authentication of the web UI. |
| `OAUTH2_CLIENTS_CONFIGURATION` | API client registry (default `config/oauth2_clients.yml`). |
| `WEBAPP_ROOT_PATH`, `WEBAPP_ALLOWED_HOSTS` | URL prefix (default `/eurobot/`) and accepted host names. |
| `APPROVAL_DATABASE_URL`, `PERMISSIONS_DATABASE_URL` | Needed by the underlying commands. |
| Chat platform variables, `BOT_NAME` | Needed so the web process can post notifications to chat. |

Requests from the web UI run as the LDAP user in the `$webui` pseudo-channel, and from the API as the OAuth2
`client_id` in `$api`. Grant them access with permission rules.

## Web UI

Log in with your LDAP credentials at `/login`.

| Page | Description |
|---|---|
| `/onboarding` | Dashboard of the available actions. |
| `/onboarding/github` | GitHub Copilot onboarding. The team is chosen from a tree of the enterprise teams (a plain text field if GitHub cannot be reached). |
| `/onboarding/github/bulk` | Onboard several people at once. Usernames can be validated first. |
| `/onboarding/move/bulk` | Move several people to another team at once (one `onboard move` per row, each queued for approval). Rows are email + team; supports the team tree and pasting from Excel. Needs a permission rule for `commands.onboarding.team:onboard_move` that covers the `$webui` channel. |
| `/onboarding/jetbrains`, `/crowd`, `/slack`, `/offboard` | Forms for the matching commands. |
| `/admin/permissions` | Permission rule management: list and filter, create, edit, delete, and a change history. Gated by the rule `webapp.routers.permissions:manage`. A save that would remove your own access is refused, and the page's own rule cannot be deleted or renamed. |
| Reload permissions | Dashboard action that invalidates the web process's cache. Run `permissions reload` in chat for the bot. |

## REST API

Interactive documentation is at `/docs`.

### Authentication

OAuth2 client credentials. Clients are configured in `config/oauth2_clients.yml`.

```sh
curl -X POST <base>/api/oauth/token \
     -d grant_type=client_credentials -d client_id=<id> -d client_secret=<secret>
# {"access_token": "...", "token_type": "bearer", "expires_in": ...}
```

Send the token as `Authorization: Bearer <token>`.

### Endpoints

All are `POST` with a JSON body (except where none is listed). Each returns `success`, `exit_code`, `output`,
`messages` and `error`.

| Endpoint | Body | Runs |
|---|---|---|
| `/api/onboarding/github` | `username`, `email`, `team` | `onboard github` |
| `/api/onboarding/github/bulk` | `items`: list of the above | `onboard github` once per item, independently. Returns a list of results. |
| `/api/onboarding/jetbrains` | `email`, `team_name` | `onboard jetbrains` |
| `/api/onboarding/crowd` | `username`, `team` | `onboard crowd` |
| `/api/onboarding/slack` | `email`, `member_ids` | `onboard slack` |
| `/api/onboarding/offboard` | `email` | `offboard` |
| `/api/onboarding/github_check` | none | `onboard github check` |
| `/api/admin/permissions/reload` | none | `permissions reload` |

A successful call to an onboarding endpoint means the request was **queued**, not executed.
