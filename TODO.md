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
6. **Deprecated `datetime.utcnow()`** in `account_storage.py` / `accounts.py`: use
   `datetime.now(timezone.utc)` (also removes the naive/aware mix).
7. **`.gitignore`**: `[Ss]cripts` ignores `scripts/`; add `!/scripts/`.
8. **Single notification sender**: `backend.notifications.set_sender` supports only one sender
   and the web process has none (see the notifications section above).
9. The **`bot github pending-invitations`** command seems to only show the first 100 pending invitations (the GitHub API paginates at 100). Use `get_paginated` to fetch all pages.
10. **`bot github pending-invitations`**: the command shows the `login` of the invited user, but not the `email` (which is often more useful to identify them). Since these are already from the bot, use the database to fill in the email.
11. `bot github members` shows the `login` of the member, but sometimes no email exists on GitHub. Use the database to fill in the email. Add maybe a column that shows the source of the email (if it's from GitHub, or from the bot's database).

## Other chat platforms

Mattermost, Discord, Telegram and Teams gaps are tracked in `TODO-chat-platforms.md`.
