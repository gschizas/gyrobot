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
4. **`GitHubApi.get_user_details` makes two calls**: an unauthenticated `requests.get`
   (60/hour per IP limit, easily hit by bulk onboarding), then the authenticated one. Drop the first.
5. **Inconsistent validation errors** in `_github_validate`: user-not-found returns a message, but
   bad team / email domain raise `RuntimeError`. Return strings for all.
6. **No tests**: add pytest coverage for `_parse_id_spec`, `convert_slack_emoji`,
   `flatten_team_tree` and the invitation expiry decision.
7. **Deprecated `datetime.utcnow()`** in `account_storage.py` / `accounts.py`: use
   `datetime.now(timezone.utc)` (also removes the naive/aware mix).
8. **`.gitignore`**: `[Ss]cripts` ignores `scripts/`; add `!/scripts/`.
9. **Single notification sender**: `backend.notifications.set_sender` supports only one sender
   and the web process has none (see the notifications section above).

## Mattermost gaps (`src/chat/mattermost.py`)

Compared with `chat/slack.py`:

**Breaks approval-gated / secured commands (highest priority)**
- `channel_name` is not implemented on `MattermostConversation` (abstract attribute only), so
  `check_security`, `security_check` and `requires_approval` fail with `AttributeError`.
  Needs a `channels.get_channel` lookup (+ cache) returning a display name with the `#`/`🔒`/`🧑`
  prefix convention used by the permission rules.
- `get_team_info()` returns `None`, so `Conversation.team_name` (`get_team_info()['name']`) raises
  `TypeError`; `requires_approval` calls it when enqueuing a request.
- `get_user_info()` returns `None`: `_approver_name`/`_requester_name` fall back to the raw user id,
  and anything reading `real_name` etc. gets nothing. Use `users.get_user` (+ `users_cache`).
- `send_ephemeral` signature differs from Slack (`text, blocks, is_error, icon_emoji` all required,
  no defaults), so calls like `send_ephemeral(text=...)` fail.

**Stubs (`pass`)**
- `send_file` (used by `send_table` on Slack, `unicode`, `kudos view`, Excel exports): use
  `files.upload_file` then a post with `file_ids`.
- `send_fields` (used by `usernotes`) and `send_blocks`: map to message attachments / Markdown.

**Partial / incorrect**
- `send_table` and `send_tables` ignore `table_format` (no Excel/zip/Markdown file output,
  `SEND_TABLES_AS_EXCEL` is ignored) and post to `self.channel_id` only; no `channel=` support.
  Large tables may exceed Mattermost's post size limit (16383 chars) and need splitting/file upload.
- `send_text` ignores `is_error` and `icon_emoji` (no error styling).
- `permalink` is always empty (`Message.permalink`), so error reports ("Exception caused by ...") have no link.
- `handler` ignores `post`, `status_change` etc. events by design, but also: no filtering of the bot's
  own posts (risk of reply loops), no filtering of edited/system posts, and uses `print()` instead of `logger`.
- `chat_connect` hardcodes `'scheme': 'http'` (should be configurable/https), and `MATTERMOST_API_URL`
  is passed as the host (no port/basepath options).
- Leftover dev artifacts: the hardcoded `"eurobot test"` message, the `tests()` function with a
  hardcoded server URL/team/channel IDs, and `"Authorization": f"******"` placeholders (broken).
- `_mattermost_team_info`/`_preload` are unused; `users_cache`/`teams_cache`/`channels_cache` are never populated.
- Mattermost `@mention` and user-id formats differ from Slack's `<@U123|name>`; `kudos` (`EXTRACT_SLACK_ID`),
  `_extract_email` (`<mailto:...|...>` in `commands/onboarding/github.py`) and Reddit link parsing
  (`extract_username`) assume Slack formatting.
- `get_notification_sender` (`chat/__init__.py`) builds `MattermostConversation(bot_name, channel, None, None)`;
  works for `send_text`, but untested.
- Emoji shortcodes (`:white_check_mark:`) render natively in Mattermost, but custom Slack-only ones won't.

## Other chat platforms

- **Discord**: skeleton in `src/chat/discord.py` (`discord.py`, selected by `DISCORD_API_TOKEN`). Untested
  against a real server. Remaining work:
  - Enable the *Message Content* privileged intent for the bot in the Discord developer portal.
  - `send_table`/`send_tables` ignore `table_format` (no Excel/file output); `send_blocks` raises `NotImplementedError`.
  - `send_ephemeral` DMs the user (Discord ephemerals need slash-command interactions).
  - `channel_name` uses `#`/`🔒` from `@everyone` view permission; permission rules written for Slack
    channel names must be adapted; `team_id`/`team_name` map to the guild.
  - Slack-style mention/link parsing (`kudos`, `_extract_email`, Reddit link helpers) needs Discord (`<@id>`) variants.
  - The bot doesn't need the trigger word via mention; consider `@bot` and slash-command support.
- **Telegram**: skeleton in `src/chat/telegram.py` (`pyTelegramBotAPI`, selected by `TELEGRAM_API_TOKEN`).
  Untested against the real API. Remaining work:
  - Disable *privacy mode* in @BotFather, or the bot won't see normal group messages.
  - Text is sent as HTML (Slack ``` blocks and `*bold*` converted); other Slack mrkdwn (links `<url|text>`,
    `_italic_`, `~strike~`) isn't converted.
  - `send_table`/`send_tables` ignore `table_format` (no Excel/file output); `send_blocks` raises `NotImplementedError`.
  - `send_ephemeral` DMs the user (only works if they've started the bot); `send_fields` drops colours.
  - No workspace concept: `team_id` is empty and `team_name` is always `Telegram`; permission rules must
    use `#title`/`🔒title`/`🧑name <username@id>` channel names (or `*`).
  - `channel_name`/`get_user_info` do API calls (cached, never invalidated); user lookup via `get_chat_member` fails in DMs of other users.
  - Slack-style mention/link parsing (`kudos`, `_extract_email`, Reddit link helpers) needs Telegram variants.
  - Polling only (`infinity_polling`); no webhook mode.
- **Teams**: skeleton in `src/chat/teams.py` (`botbuilder-integration-aiohttp`, selected by `TEAMS_APP_ID`;
  also `TEAMS_APP_PASSWORD`, optional `TEAMS_APP_TENANT_ID`, `TEAMS_APP_TYPE`, `TEAMS_PORT`). Untested against
  a real Azure Bot registration. Remaining work:
  - Needs a public HTTPS endpoint for `POST /api/messages` (reverse proxy/tunnel) and an Azure Bot
    registration + Teams app manifest; this differs from the other platforms, which connect outbound.
  - Proactive messages (including approvals notifications) need a stored `ConversationReference`, which is
    only captured when someone messages the bot in that conversation; persisted in
    `data/teams_conversations-<LOG_NAME>.yml`. Consider pre-seeding the `notify_channel` or using
    `create_conversation` to post into a configured Teams channel by id.
  - `send_file` raises `NotImplementedError` (needs the file-consent flow or SharePoint/OneDrive); `send_blocks` too
    (use Adaptive Cards); tables are code blocks (ignore `table_format`, no Excel).
  - `send_ephemeral` replies visibly in the conversation.
  - Slack mrkdwn (`*bold*`) renders differently in Teams Markdown (`**bold**`); only the bot-authored titles use `**`.
  - `get_user_info` only knows users seen in incoming messages; no Graph API lookup (emails, real names, `@group` mapping).
  - Server binds `0.0.0.0` on plain HTTP; no health endpoint; BotFramework auth is handled by the adapter.
  - Uses `CloudAdapter` from `botbuilder-*` (Microsoft's newer replacement is the Microsoft 365 Agents SDK).
  - `team_id` is the Teams team id (or tenant id outside a team); `channel_name` uses `#channel`/`🔒group chat`/`🧑name`.
- Other platforms: copy the Discord/Telegram/Teams skeleton (conversation class + `chat_connect` + a branch in
  `chat/__init__.py` for both `get_chat_wrapper` and `get_notification_sender`).
