# Web UI and REST API

A FastAPI application with two interfaces over the same commands the chat bot uses. Both drive the real `onboard`
and `offboard` commands, so they go through the same validation, [approval queue](APPROVALS.md) and
[permission rules](PERMISSIONS.md) as chat. Requests are approved in chat. The "new approval request" announcement is
posted to the notify channel in chat, not shown in the web page.

Run with `python src/run_webapp.py <env-name>` (reads `.env.d/<env-name>.env`; the name may be omitted when
`GYROBOT_ENV` is set) or point an ASGI server at
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

Every route of the web routers requires a login by default: `webapp/auth.py` provides the `current_user` dependency
(anonymous users are redirected to `/login`; JSON endpoints answer 401), applied to whole routers, so only
`web.public_router` (`/`, `/login`, `/logout`) is open. `tests/test_web_auth.py` checks that no web route answers an
anonymous request. The dashboard greys out the actions you have no permission rule for, and hides the administration
links (`webapp/capabilities.py` reuses the real rules); this is only a hint, the commands and pages still enforce.

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
- **Secret**: a long random value (at least 32 bytes). Any of these works:

  ```sh
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n'
  openssl rand -hex 32
  ```

  PowerShell, without Python or OpenSSL:

  ```powershell
  [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).TrimEnd('=').Replace('+','-').Replace('/','_')
  ```

  Prefer the URL-safe forms (`token_urlsafe`, `-hex`, the translated base64 above): the secret is used in Basic auth
  and in form bodies, where `+`, `/` and `=` can be mangled. Never reuse a secret between clients.
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
| `/api/onboarding/crowd` | `username` (login or email), `team`, optional `groups` | `onboard crowd` |
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
| `Login`, `GithubId`, `NodeId`, `GlobalId` | GitHub login, numeric id, the legacy node id derived from it (`MDQ6...`), and the stored next-generation global node id (`U_kgDO...`, empty until backfilled) |
| `Email` | primary email |
| `Team`, `Role`, `RoleName` | canonical team, role key and display name |
| `Status` | provision status (`invited`, `active`, `removed`, ...) |
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

Rows outside these prefixes are never returned, whatever the `$filter`.

To set it up for a new consumer:

1. Add the client to `config/oauth2_clients.yml` with `scopes: [directory:read]` and restart the web process.
2. In `/admin/permissions`, create a rule:
   - **Function**: `webapp.routers.odata:list_github_users`
   - **Environment**: the global one (blank), **Role**: `default`
   - **Users**: the client id (one per line; `*` allows any client with the scope)
   - **Channels**: `$api`
   - **Extra**: `{"team_prefixes": ["<prefix>"]}`, or empty for all teams
3. Saving refreshes the web process's cache, and the API runs in that process, so it applies at once. Run
   `permissions reload` only if the chat bot should see the rule too.

Without the scope you get 403, and without the rule you get 403.

#### History feed

`GET /api/odata/GithubUserHistory` has the same columns (plus `Event`) and the same query options, but one row per
**recorded change** instead of the current state. It is the union of `account_provision_history` (`Event` =
`Provision`: login, ids and status of that change) and `account_history` (`Event` = `Account`: email and team of that
change), and each row is completed with the other stream's state at that moment (the email/team snapshot in effect,
or the GitHub provision in effect; empty when there was none yet). `Id` is `P<n>` or `A<n>`, `LastChanged` is the
time the change was recorded, and rows are oldest first by default. `IsLatest` (boolean) is `true` on the most recent
row of each person (the latest change in either stream, so it matches the current state); filter with
`$filter=IsLatest eq true` to get one current row per person. The flag is computed over all history, so it does not
change when other filters or team limits hide rows. Because earlier logins are kept in the history,
a reinvited person shows both logins here.

Team memberships have no history, so `Role` and `RoleName` are the person's **current** role in that row's team
(empty if they no longer hold it).

It is authorized separately, by the rule `webapp.routers.odata:list_github_user_history` (same setup and `extra` as
above; the same `directory:read` scope).

**Excel**:

1. *Data > Get Data > From Other Sources > From OData Feed*.
2. URL: `https://<host>/eurobot/api/odata/GithubUsers` (development: `http://localhost:<port>/api/odata/GithubUsers`,
   with `WEBAPP_ALLOW_BASIC_HTTP=1`). A filter can go in the URL, for example `?$filter=startswith(Team,'<prefix>')`.
3. Choose **Basic** authentication; the user name is the client id and the password is the client secret.
4. In the navigator, select **GithubUsers**, then **Load** (or **Transform Data**). Power Query follows
   `@odata.nextLink`, so you get all rows, not just the first 100.

Notes: Excel remembers credentials per URL (change them in *Data > Get Data > Data Source Settings*); it reads
`$metadata` first, so a 403 there means the scope or the rule is missing. **Power BI** is the same: *Get data > OData
feed*, then Basic.

**Excel troubleshooting**:

- **"Access to the resource is forbidden"**: read the real reason with `curl -u <id>:<secret> <url>`. Over plain HTTP
  it is `Basic authentication requires HTTPS` (development: set `WEBAPP_ALLOW_BASIC_HTTP=1`); otherwise the scope
  (`Missing scope`) or the rule (`Not permitted`) is missing.
- **Stale connection after a server fix**: Power Query caches responses, including `@odata.nextLink`, and credentials
  per URL. Clearing credentials (*Data Source Settings > Clear Permissions*) is not enough. Also clear the cache
  (*Data > Get Data > Query Options > Global > Data Load > Clear Cache*, and the same under *Current Workbook >
  Data Load*), then delete the old query and create it again. A symptom is Excel (or a proxy such as Fiddler) asking
  only for URLs without the `/eurobot` prefix.
- **Pinning the OData version**: a blank query with
  `OData.Feed("<base>/api/odata/GithubUsers", null, [Implementation = "2.0"])` makes Excel use the OData v4 reader,
  which follows `@odata.nextLink` as the server returns it.
- **Checking what the server returns**: `@odata.context` and `@odata.nextLink` must start with the public URL, for
  example `https://<host>/eurobot/api/odata/`:

  ```sh
  curl -s -u <id>:<secret> "https://<host>/eurobot/api/odata/GithubUsers?\$top=1" | grep -o '"@odata[^,]*'
  ```
