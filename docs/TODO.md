# TODO

## Notifications for the Web UI / REST API

`backend.notifications.notify()` currently only reaches the chat platform
(Slack/Mattermost), through the sender registered in `__main__.py`
(`chat.get_notification_sender`). Background events such as GitHub invitation
accepted/expired are not visible in the web UI or API. Options:

- Persist notifications in a table (e.g. `notifications`: id, created_at, text, read)
  from `notify()`, and show them on the web dashboard (and a `GET /api/notifications` endpoint).
- Support multiple senders in `backend.notifications` (chat, webhook, email via
  `backend.email_logging`) instead of a single one.
- Add a webhook callback URL per OAuth2 client in `config/oauth2_clients.yml` so API
  consumers get pushed events.
- Note: the web app can run in a separate process from the bot, so an in-memory
  sender isn't enough; the database is the shared channel.

## Review suggestions

1. **Repeated notifications on assignment failure**: if `add_users_to_ent_team` fails, the
   provision stays `invited` and every background cycle retries and re-notifies. Record
   `failed_at`/`last_error` in the provision data (or use a `failed` status) and only notify on change.
2. **Case-sensitive login matching** in `check_github_invitations` (`username in all_user_logins`):
   compare lowercased on both sides (older provisions may have the wrong casing).
3. **Approvals-channel notification on failure**: the exception path in `_approve_one`
   (`commands/approvals.py`) should also notify the approvals channel.
4. **Inconsistent validation errors** in `_github_validate`: user-not-found returns a message, but
   bad team / email domain raise `RuntimeError`. Return strings for all.
5. **No tests**: add pytest coverage for `_parse_id_spec`, `convert_slack_emoji`,
   `flatten_team_tree` and the invitation expiry decision.
6. **Single notification sender**: `backend.notifications.set_sender` supports only one sender
   and the web process has none (see the notifications section above).
7. `bot github members` (now GraphQL-based) shows no email when none exists on GitHub. Use the database to fill in the email. Add maybe a column that shows the source of the email (if it's from GitHub, or from the bot's database).

## Planned features and design notes

1. **Crowd onboarding in gyrobot** (chat bot and web UI): incorporate the existing Crowd onboarding code.
   **Do not write any Crowd onboarding code until the existing scripts have been pasted.** They mostly validate
   that the account exists in AD/LDAP before adding it, and then assign the proper team. `onboard crowd` and
   `backend/providers/crowd.py` are currently stubs.
2. **Secrets storage**: a pluggable secret store now exists (`backend/secret_store`, see `SECRET-STORE.md`) with
   systemd, directory, `pass`, keyring and Azure Key Vault backends; remaining work is choosing a backend, moving the
   real secrets, and routing the `config/*.credentials.yml` files through it.
   (Options and trade-offs are in `SECRETS-OPTIONS.md`; systemd credentials need systemd 250+,
   so they're parked until the server leaves Ubuntu 22.04; see `SYSTEMD-CREDENTIALS.md`.) Plain-text files holding passwords/tokens are not good enough. The server runs on Linux, so
   there is no DPAPI equivalent. Evaluate alternatives (e.g. systemd credentials, an OS keyring or secret service,
   Vault or another secrets manager, or encrypting at rest with a key kept outside the config directory).
3. **`accounts.name` column**: it is not used properly (currently the GitHub username is written there), and it may
   not be needed at all. The GitHub username (login) should not live there; if anything it should be a calculated
   column derived from the account's GitHub provision (`data->>'username'`, or looked up by the stored `github_id`
   so that it survives renames). Decide whether to drop `name` or give it a proper meaning (the person's real name).
4. **Backfill `invitation_id`** (and `github_id`) in existing GitHub provisions: rows created before the
   `github_cancel` command lack it; `github_cancel` copes by matching on login/email, but the id could be filled in
   from the pending invitations for `invited` rows.
5. **`ProvisionRequest` cleanup** (`backend/providers/base.py`, formerly `Account`):
   - `userid` and `team` are required, but `onboard slack`, `onboard crowd`, `onboard jetbrains` and `offboard`
     build it with only `name` and `email`, which raises `TypeError`. Give both a default of `''`.
   - Rename the `provision_data` field to `result_data`, and the `account` parameter of the provider functions to
     `request`.
   - Tidy the old `Account as ProviderAccount` import aliases.
6. **Permissions web page**: a page to manage permissions. Gather all functions that need permissions
   (reflection over the registered commands / `check_security` and `requires_approval` decorators?). Open question:
   how to handle roles. It should present a list of people to choose from, either from Slack or from the
   active directory.
7. **Store active directory users with their domain**: store e.g. `jdoe@example.com` instead of just `jdoe`.
8. **Move to Alembic for database migrations**. All the databases (approval, permissions, kudos, survey) are one
   PostgreSQL database, so use a single migration history.
   - Add `alembic` and `sqlalchemy` (with a `postgresql+psycopg://` URL); `env.py` loads `.env.d/<name>.env` through
     `backend.secret_store.load_environment`. Write migrations as plain SQL with `op.execute()`; no ORM models or
     autogenerate are needed, so the code can stay on psycopg (and Pydantic, if adopted).
   - Baseline `0001`: the schema as it is today, written with `IF NOT EXISTS`, then `alembic stamp 0001` on every
     existing database. Taken from the code's `_SCHEMA` strings for `accounts`, `account_provisions`,
     `account_provision_history`, `account_history` and `approval_requests`; from `scripts/migrate_permissions.py`
     for `permission_rules`; and from `pg_dump --schema-only` for `kudos` (gyrobot-only) and the survey tables
     `"Votes"`, `"Answers"` and `"Receipts"` (created by the separate questionnaire app through Flask-SQLAlchemy
     `create_all`; gyrobot only reads them).
   - Make the next changes real migrations: `accounts.team` and `account_history`.
   - Delete the `_SCHEMA` strings and the table creation in `approval._connect`; replace `scripts/check_schema.py` with
     `alembic current` / `alembic check`; document `alembic upgrade head` as a deploy step (maybe in the Docker
     entrypoint). Decide whether the bot, web UI and API refuse to start, or only warn, when the database is behind.
   - Once the questionnaire app is retired, the survey tables can be dropped from the baseline.
9. **Leftovers from the removed `cheese` and `too_many_posts` commands** (code and docs are already removed):
   - Remove `CHEESE_DATABASE_URL` and `GYROBOT_DATABASE_URL` from the `.env.d` files, `data/cheese_agent.yml` from
     the server, and any permission rules (`permission_rules`) naming the two commands.
   - Optionally drop the `"machineState"` and `"jobQueue"` tables and `public.submissions`; keep them out of the
     Alembic baseline.

## Other chat platforms

Mattermost, Discord, Telegram and Teams gaps are tracked in `TODO-chat-platforms.md`.
