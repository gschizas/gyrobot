"""Web UI + REST API interfaces for onboarding commands.

This package exposes a subset of the chat bot's ``onboard``/``offboard``
commands (see ``commands/onboarding``) over HTTP, without modifying the
commands themselves:

* A server-rendered Web UI, authenticated against an LDAP directory
  (``webapp.auth_ldap``), for humans.
* A JSON REST API, authenticated with OAuth2 client-credentials
  (``webapp.auth_oauth2``), for machine-to-machine integrations.

Both interfaces dispatch through :func:`webapp.command_runner.run_bot_command`,
which drives the existing Click command tree (``commands.gyrobot``) via
``click.testing.CliRunner`` -- the same mechanism ``src/__main__.py`` uses for
chat messages -- using a headless :class:`webapp.chat_adapter.HeadlessConversation`
in place of a real Slack/Mattermost conversation. This means permission checks
(``check_security``/``requires_approval``) and the approval queue behave
identically to chat-issued commands; administrators grant access by adding
``permission_rules`` rows for the ``$webui``/``$api`` pseudo-channels (see
``backend/permissions.py``).
"""
