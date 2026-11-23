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
| `LDAP_SERVER`, `LDAP_USERNAME_PATTERN`, `LDAP_AUTHENTICATION_TYPE` | LDAP authentication of the web UI: the server, the bind name with `{}` for the username (`DOMAIN\{}`, `{}@domain.corp` or a DN), and `NTLM` (default) or `SIMPLE`. |
| `OAUTH2_CLIENTS_CONFIGURATION` | API client registry (default `config/oauth2_clients.yml`). |
| `WEBAPP_ROOT_PATH`, `WEBAPP_ALLOWED_HOSTS` | URL prefix (default `/eurobot/`) and accepted host names. |
| `APPROVAL_DATABASE_URL`, `PERMISSIONS_DATABASE_URL` | Needed by the underlying commands. |
| Chat platform variables, `BOT_NAME` | Needed so the web process can post notifications to chat. |

Requests from the web UI run as the LDAP user in the `$webui` pseudo-channel, and from the API as the OAuth2
`client_id` in `$api`. Grant them access with permission rules.

## Web UI

Log in with your LDAP credentials at `/login`. End users: see the [user manual](WEB-UI-MANUAL.md).

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

#### Creating a client

Copy `config-examples/oauth2_clients.example.yml` to `config/oauth2_clients.yml` and add one entry per consumer:

```yaml
clients:
  powerbi-directory:
    secret: "<random>"
    description: "Power BI GitHub users report"
    scopes: [directory:read]
```

- **Client id**: the key under `clients:`. Any short, unique, stable string. It is also the username for HTTP Basic
  auth and the user name that permission rules match, so renaming it breaks both.
  - Use one client per consumer (`powerbi-hr-report`, `export-script`) so each has its own scopes and limits and can be
    revoked separately.
  - Use lowercase letters, digits and hyphens. No `:` (it breaks Basic auth) and no spaces.
  - Do not put secrets or private organisation names in it; it appears in logs.
- **Secret**: a long random value, for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- **Scopes**: `onboarding` allows the write endpoints below, `directory:read` allows `GET /api/odata/*`. A client with
  no `scopes` gets `onboarding` only. Give read-only consumers `directory:read` alone.

The registry is cached for the life of the web process; restart it after editing.

### Endpoints

All are `POST` with a JSON body (except where none is listed). Each returns `success`, `exit_code`, `output`,
`messages` and `error`.

| Endpoint | Body | Runs |
|---|---|---|
| `/api/onboarding/github` | `username`, `email`, `team`, optional `role` (a role key) | `onboard github` |
| `/api/onboarding/github/bulk` | `items`: list of the above | `onboard github` once per item, independently. Returns a list of results. |
| `/api/onboarding/jetbrains` | `email`, `team_name` | `onboard jetbrains` |
| `/api/onboarding/crowd` | `username`, `team` | `onboard crowd` |
| `/api/onboarding/slack` | `email`, `member_ids` | `onboard slack` |
| `/api/onboarding/offboard` | `email` | `offboard` |
| `/api/onboarding/github_check` | none | `onboard github check` |
| `/api/admin/permissions/reload` | none | `permissions reload` |

A successful call to an onboarding endpoint means the request was **queued**, not executed.

### GitHub users listing (OData)

`GET /api/odata/GithubUsers` lists GitHub users, one row per person and team membership (people without a membership
appear once, with their main team and an empty role). Read-only; every status is listed (`Status` column).

| Property | Meaning |
|---|---|
| `Id` | `<login>\|<team>`, the entity key |
| `Login`, `GithubId`, `NodeId` | GitHub login, numeric id, and the legacy global node id derived from it |
| `Email` | primary email |
| `Team`, `Role`, `RoleName` | canonical team, role key and display name |
| `Status` | provision status (`invited`, `assigned`, `active`, `removed`, ...) |
| `LastChanged` | latest change of the account, the GitHub provision or the membership |

Only the **current** login is shown. Someone who lost their GitHub account and was reinvited keeps one row with the
new login (see `docs/TODO.md`, item 15).

Supported query options: `$filter` (`eq ne gt ge lt le`, `and or not`, parentheses, `startswith endswith contains`),
`$orderby`, `$select`, `$top` (default 100, at most 1000), `$skip`, `$count=true`. Anything else returns an OData
error (HTTP 400). Page through the results by following `@odata.nextLink`. `$metadata` is served for Excel and
Power BI. The team prefix is just a filter, or the shortcut `?team_prefix=<prefix>`:

```sh
curl -u <client-id>:<secret> "<base>/api/odata/GithubUsers?\$filter=startswith(Team,'<prefix>')&\$top=100"
```

**Authentication**: a bearer token (as above) or HTTP Basic with the client id and secret (Excel and Power BI cannot
do the client-credentials flow). Basic is refused over plain HTTP unless `WEBAPP_ALLOW_BASIC_HTTP=1` (development
only); behind a proxy, make it send `X-Forwarded-Proto`. The client needs the `directory:read` scope.

**Authorization**: the client also needs a permission rule for function `webapp.routers.odata:list_github_users`,
channel `$api`, with the client id in `users`. Without a rule, access is denied. Optional `extra` limits the teams:

```json
{"team_prefixes": ["platform", "data"]}
```

Rows outside these prefixes are never returned, whatever the `$filter`. Add the rule in `/admin/permissions` and run
`permissions reload` for the bot (the web process picks it up on its own reload/restart).

**Excel / Power BI**: use *Get data > From OData feed* with `<base>/api/odata`, choose *Basic* authentication and
enter the client id and secret.
