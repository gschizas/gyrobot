# Web UI user manual

A short guide for people who use the onboarding web UI. For setup and the REST API see
[WEB-AND-API.md](WEB-AND-API.md).

## The basics

- **Logging in**: open the web UI and sign in with your normal directory (LDAP) username and password. Use
  **Logout** when you are done on a shared computer.
- **Nothing happens immediately.** Every onboarding, offboarding and move form only *queues a request*. A designated
  approver approves it in chat (`approvals list`, `approvals approve <id>`), and only then is the change made.
  "Success" on the result page means "queued".
- **Permissions.** You see the pages everyone gets, but a form is refused if you are not allowed to make that kind of
  request. If you need access, ask an administrator to add you to the matching permission rule
  ([PERMISSIONS.md](PERMISSIONS.md)).
- Anything you can do here you can also do in chat (`onboard ...`, `offboard ...`); the web UI is simply easier for
  teams and for many people at once.

## Onboarding dashboard

After logging in you land on the **Onboarding** page, which lists every action. Pick one.

### Onboard a colleague (single person)

| Form | You enter | Result |
|---|---|---|
| **GitHub Copilot** | GitHub username, email address, team, optionally a role | An invitation to the GitHub enterprise and, once accepted, assignment to the team. The role is stored with the team. |
| **JetBrains IntelliJ IDEA** | Email address, team name | A licence of that team's pool is assigned. The team must have a free licence. |
| **Crowd** | Login or email, canonical team, optional extra groups | A Crowd user in the team's groups; the welcome email is sent. |
| **Slack** | Email address, member IDs (comma-separated) | Slack workspace membership. |
| **Offboard** | Email address | Removal of all the person's active provisions, and Slack deactivation. |

Notes:

- On the GitHub form, **choose the team from the tree** (click to expand). It shows the enterprise teams with their
  parents. If GitHub cannot be reached, you get a plain text field instead; type the team slug.
- The email address must belong to an allowed domain.
- The team is the canonical team name used by the company (see your administrator for the list).

### Bulk onboard: GitHub Copilot

For several people at once.

1. Fill in one row per person: username, email, team. You can **paste a range of cells from Excel**
   (username / email / team columns, in that order).
2. Optionally use **Validate** to check that each GitHub username exists before sending.
3. Submit. Each row becomes its own approval request, and a row that fails does not stop the others. The result
   page shows one line per person.

### Bulk move

Changes the team of several colleagues. Each row is an email address and the new team; pasting from Excel works the
same way (email / team columns). Every row is queued separately.

### Fill in missing emails of GitHub members

Some GitHub enterprise members have no verified email on GitHub and none recorded in our database.

1. The page loads the list from GitHub. This can take a while; a progress message is shown and the page refreshes
   when ready. **Refresh from GitHub** reloads it.
2. Use the filter box to search by username or team, and click a column title to sort. The list is paged.
3. Type the email of each person you know. Leave the others blank; blank rows are skipped.
4. **Submit all filled-in rows.** Each email is queued as a separate approval request.

## Administration (administrators only)

These links appear on the dashboard only if you have the right.

- **Manage permission rules**: list, filter, create, edit and delete rules (who may run which function, in which
  channel), and see a change history. A save that would remove your own access is refused.
- **Reload permissions**: makes the web UI pick up rule changes made in the database. The chat bot keeps its own
  cache; run `permissions reload` in chat for that.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Login fails | Wrong LDAP username or password; the directory server may be unreachable. |
| "Not allowed" after submitting | No permission rule covers you for that function in the web UI channel. |
| Result says the request was queued but nothing changed | It is waiting for an approver. |
| The team tree is a plain text field | GitHub could not be reached; enter the team slug by hand. |
| Missing-emails page stays on "Loading" | GitHub is slow or rate-limited; wait, then use **Refresh from GitHub**. |
