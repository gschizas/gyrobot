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
8. **Move all database access to SQLAlchemy + Alembic**. Everything the bot owns is one PostgreSQL database, so use
   a single migration history, and move the queries from psycopg to SQLAlchemy as well (not only the schema).
   Do it one functional group at a time, least complicated first, each as its own commit:
   1. **DONE (pending a test on the real database)** kudos (`kudos` table, `commands/kudos.py`) - this one also sets up Alembic (`alembic` and `sqlalchemy`
      dependencies, a `postgresql+psycopg://` URL, `env.py` using `backend.secret_store.load_environment`) and the
      baseline `0001`; the kudos table definition comes from `pg_dump --schema-only -t kudos`.
   2. **DONE (pending a test on the real database)** permissions (`permission_rules`, `backend/permissions.py`, DDL now in `scripts/migrate_permissions.py`).
   3. onboarding / offboarding / approvals (`accounts`, `account_provisions`, `account_provision_history`,
      `account_history`, `approval_requests`). Make `accounts.team` and `account_history` real migrations.
   - For each group: define the SQLAlchemy models, write the migration (stamp it on existing databases with
     `alembic stamp`, because the tables already exist), switch the queries over, and delete the old `_SCHEMA`
     strings and table creation.
   - At the end: replace `scripts/check_schema.py` with `alembic current` / `alembic check`; document
     `alembic upgrade head` as a deploy step (maybe in the Docker entrypoint). Decide whether the bot, web UI and API
     refuse to start, or only warn, when the database is behind.
9. **Leftovers from the removed `cheese`, `too_many_posts` and `survey` commands** (code and docs are already removed):
   - Remove `CHEESE_DATABASE_URL`, `GYROBOT_DATABASE_URL`, `QUESTIONNAIRE_DATABASE_URL` and `QUESTIONNAIRE_FILE` from
     the `.env.d` files, the questionnaire YAML from `data/` and `data/cheese_agent.yml` on the server, and any
     permission rules (`permission_rules`) naming the three commands.
   - Optionally drop the `"machineState"`, `"jobQueue"`, `"Votes"`, `"Answers"` and `"Receipts"` tables and
     `public.submissions`; they stay out of the Alembic baseline.

## Other chat platforms

Mattermost, Discord, Telegram and Teams gaps are tracked in `TODO-chat-platforms.md`.
