# Reddit commands

All of these need `SUBREDDIT_NAME` in the environment (the subreddit being moderated). `make` also needs
`REDDIT_ALT_USER`. They use two Reddit sessions:

- the **moderator account** for reading (modqueue, usernotes, wiki pages), and
- the **alternate (bot) account** for actions taken as a moderator on user content (`nuke user`, `make`).

Wherever a command takes a username or thread, you can paste what Slack gives you: `<https://reddit.com/u/foo|foo>`,
a thread URL, a Reddit share link (`/s/...`) or the bare id.

## `modqueue`

| Command | Description |
|---|---|
| `modqueue` / `modqueue length` | Number of items in the modqueue (the default subcommand). |
| `modqueue posts` | List the posts in the modqueue. |
| `modqueue comments` | List the comments in the modqueue. |
| `modqueue grouped` | Authors with more than one item in the modqueue, most items first. |

## `usernotes <user> [verbose]`

Shows the Toolbox usernotes of a user, read from the subreddit wiki (`usernotes` and `toolbox` pages), coloured by
note type. Add a second argument for the long format.

## `nuke`

Bulk removal of content.

| Command | Description |
|---|---|
| `nuke thread <thread_id>` (alias `nuke post`) | Removes the submission and all its comments except distinguished ones, then locks it. The removed comment ids are remembered so the action can be undone. |
| `nuke thread_undo <thread_id>` | Approves again the comments removed by `nuke thread`. |
| `nuke user <username> [timeframe] [-s\|-p\|--submissions\|--posts]` | Removes the user's comments from the last timeframe (default 3 days). Accepts natural language: `48 hours`, `2 months`, `a week`, `forever`. With `-s`/`-p` submissions are removed too. Uses the alternate account. Reports a shadowbanned user. |
| `nuke ghosts <thread_id>` (alias `nuke ghost`) | Removes the comments in a thread whose authors are deleted accounts. |

## `archive <username>`

Submits the user's profile pages and every post and comment to archive.is. Replies with two files: the list of
requested URLs and the list of archive URLs. Use it before nuking a user, since the user may delete the account
afterwards.

## `history <username>`

Returns the user's comment history in the subreddit, including deleted comments, as a text file. The data comes from
Pushshift.

## `comment_source <comment_id_or_url>`

Returns the raw Markdown source of a comment as a file.

## `deleted_comment_source <comment_id...>`

Returns the source of comments even if they were deleted. Takes one or more comment ids. The data comes from
Pushshift.

## `configure_enhanced_crowd_control` (aliases `order66`, `order_66`)

Manages the list of threads monitored by the enhanced crowd control job. The list is stored in
`config/enhanced_crowd_control.yml`, per subreddit (the file is created with a template entry on first use).

| Command | Description |
|---|---|
| `... list` (alias `show`) | Numbered list of monitored threads, with the action (remove or approve), thread date and monitoring period. |
| `... add <thread_id>` | Adds a thread. Threads of other subreddits are refused. |
| `... del <thread_id\|number>` (aliases `delete`, `remove`) | Removes a thread, by id/URL or by its number in the list. |

## Wiki-driven posting: `make`

Needs `REDDIT_ALT_USER`. Both commands read a wiki page whose first line is `# Title`, second line is blank, and the
rest is the Markdown body. A page can be reused for any number of posts. An optional last argument selects a wiki
revision (the latest by default).

| Command | Description |
|---|---|
| `make post <thread_id\|NEW> <wiki_page> [revision_id]` | `NEW` creates a stickied post with the title and body from the page. An existing thread id has its text updated. Replies with the link. |
| `make sticky <thread_id> <wiki_page> [revision_id]` | Creates or updates the stickied moderator comment on a thread from the page. |

## Other commands

| Command | Description |
|---|---|
| `add_domain_tag <url> <#color>` | Adds a colour tag for a domain to the Toolbox wiki configuration. |
| `add_policy <title>` | Appends a minor policy change (decided in the mod policy channel) to the policy wiki page. Uses `REDDIT_POLICY_SUBREDDIT` and `REDDIT_POLICY_PAGE` (defaults: the moderated subreddit and `mod_policy_votes`). |
| `youtube_post_info <url>` | Finds the YouTube channel/media URL of a post. |
| `unicode_post <thread_id>` | Lists the Unicode code points of a post title (to spot look-alike characters). |
