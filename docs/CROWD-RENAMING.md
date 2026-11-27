# Renaming Crowd groups, and replacing the special access groups

A plan, not an implementation. Nothing here has been run. Items marked **verify** are from memory or from
vendor documentation and must be confirmed on the real servers before the plan is relied on.

Goals:

1. Rename some Crowd groups so they line up with the canonical teams (see `team_mapping.yml`).
2. Stop depending on special groups such as `erb-ocp-dev-anonymous` (under `erb-ocp-anonymous`), used to give
   Bitbucket access, and the similar one for Confluence (licensing), by using something more explicit.

## 1. How the applications refer to a Crowd group

Every Atlassian application that authenticates against Crowd (Jira, Confluence, Bitbucket Server, Bamboo, and also
Fisheye/Crucible) sees the directory through the same small model: users, groups and memberships. It keeps its own
configuration (permission schemes, space and project permissions, repository permissions, notification schemes,
workflows, saved filters, licence use, ...) and in every one of those places the group is stored **by name**, as a
plain string, in the application's own database. There is no shared internal id: Crowd itself identifies a group by
name inside a directory, and the applications copy that string.

So the premise is correct: permissions are given to the name. The consequences:

- A renamed group is, for each application, a *new* group with no permissions, and the old name becomes a dangling
  reference (the permission rows still exist but match nobody, or the application complains that the group is gone).
- Nothing in Crowd updates those references. Each application has to be fixed on its own.
- Atlassian documents group rename as *unsupported* in the self-managed products (Confluence: CONFSERVER-9159, an open
  feature request, with a manual database procedure in the knowledge base; the same is true of Jira, Bitbucket and
  Bamboo **verify**). Only Atlassian's cloud admin has a rename call that rewrites the references.
- Crowd itself: **verify** whether the admin console and REST API (`/rest/usermanagement/1/group`) can rename a group
  in a *Crowd-internal* directory at all. I do not believe the REST API has a group rename call. For a delegated
  (LDAP/AD) directory the group is renamed in AD and Crowd only follows it.

### What else consumes Crowd groups

I can only see this repository, not the servers. Known consumers:

| Consumer | How it uses the group name | Where to look |
|---|---|---|
| Jira | Global permissions, permission schemes, project roles, notification schemes, issue security, workflows (conditions and validators), saved filters and dashboards (sharing), service desk teams | Admin UI; the database tables behind them (`schemepermissions`, `projectroleactor`, `notification`, `filtersubscription`, `sharepermissions`, ...) |
| Confluence | Global permissions, space permissions, page restrictions (user/group restrictions on individual pages), licence use | `spacepermissions`, `content_perm`; Atlassian KB "How to rename a group and preserve its permissions" |
| Bitbucket Server | Global, project and repository permissions, branch permissions and merge checks, default reviewers, hook scopes | Admin UI; `sta_*permission*` tables; the REST API under `/rest/api/1.0/admin/permissions/...` |
| Bamboo | Global, plan and deployment-project permissions | Admin UI |
| Subversion | Group references in the `authz` file (`@group = ...`), resolved through the Apache module authenticating against Crowd | The `authz` file(s) on the Subversion host |
| Fisheye/Crucible, Jira Service Management, plugins | Their own permission schemes and licence rules | Admin UI of each |
| Other things that may use Crowd (Jenkins, Artifactory, Nexus, SonarQube, OpenShift OAuth/group sync, the wiki, ...) | Same: group names, often in role-mapping or group-sync settings | To be found, see the discovery step |
| **This bot** | `team_mapping.yml` (`crowd:` section: canonical team → Crowd groups), `provisions` rows of the `crowd` resource, `crowd_users.yml` (`@group` permission rules, which come from Crowd group names), the Crowd group tree cache | The repository |

### Discovery (first step, read-only)

You asked me to check if there is anything else. From here I cannot; the authoritative list is in Crowd:

1. **Crowd admin console → Applications**: every application registered with Crowd, with the directories and
   *group mappings* it uses. An application that has an **application account** but is not on your list is the
   thing to find.
2. Crowd's database tables `cwd_application`, `cwd_app_dir_mapping` and `cwd_app_dir_group_mapping`
   (**verify** the names for your Crowd version) list the same, plus which groups an application may authenticate.
3. Crowd's audit/last-authentication information per application (and the Crowd access log) shows which
   applications *actually* authenticate people lately, which catches the ones nobody remembers.
4. Ask for anything that authenticates through Apache `mod_authnz_crowd` or a Crowd SSO filter (typical for
   Subversion, internal web tools).

Outcome: a table "application → how it references groups → how I change that" for each group being renamed.

## 2. Approaches for a rename

### A. Rename in place (not recommended)

Rename the group in the source directory and fix every reference, application by application, in one window.

- Needs an outage window, because between the rename and the last fix people lose access.
- The per-application fixes are manual UI work or unsupported database updates (Confluence's procedure is
  documented, the others are not). Page restrictions in Confluence and saved filters in Jira are the ones that get
  forgotten.
- No safe rollback after the fact besides renaming back and re-fixing.

### B. Add the new name next to the old, move the permissions, then retire the old (recommended)

Use **group nesting** so that the new name works immediately, with nothing lost:

1. Create the new group (canonical name) in Crowd.
2. Make the *new* group a **child** of the *old* one. Members of a child group are members of its parent, so
   anyone put in the new group gets everything granted to the old name, and nothing needs to be moved on day one.
   (Direction matters: old = parent, new = child. The reverse would give the new group's members nothing.)
3. Check that nesting works end to end. It must be enabled on the Crowd directory **and** on the directory
   entry in each application (Jira, Confluence, Bitbucket have a "nested groups" setting per user directory;
   Bamboo and Subversion **verify**). If an application does not resolve nested groups, approach B does not work
   for it and it needs a direct copy of the memberships in step 4 instead.
4. Copy memberships: add every *direct* member of the old group to the new one. (The bot can do this; see §4.)
5. Move the **bot** to the new name: update `team_mapping.yml` (`crowd:` canonical team → new group); from then on
   `onboard crowd` and `onboard move` only touch the new group. Existing members stay in the old one through
   step 7.
6. Per application, re-point each reference from the old name to the new one at a convenient moment (this is
   the manual part, and can be spread over weeks because both names work meanwhile). Keep a checklist per
   application.
7. When the last reference is gone: remove the old group from the parents/children it has, then delete it
   (or leave it empty, see below), and drop the nesting link.

Properties: no outage, rollback is just "don't take the next step", and each application can be done by its own
admin on its own schedule. The cost is a period during which two names exist and the group tree (`onboard crowd
teams`) shows the new group under the old one, which is the intended temporary look.

Special cases:

- A group with **several parents** (common in the Crowd tree here) keeps those parents on the old group; the new
  group inherits everything through the old one, so nothing is duplicated. At step 7 decide where the new
  group goes (usually the same parents).
- Groups that are **delegated** to AD: nest them only if Crowd is allowed to write memberships for them. For a
  read-only AD directory create the new group in a Crowd-internal directory and nest *across* directories
  (**verify**: Crowd normally allows nesting only inside one directory). If it does not, rename in AD and use
  approach A for that group.
- Groups referenced only in **Subversion** `authz`: usually a one-line change per rule; do it in step 6.

### C. Use an alias layer instead of renaming

If the objective is only that *the bot and people* use the canonical names while applications keep the legacy names,
don't rename: keep the Crowd names and put the canonical name in `team_mapping.yml`. This is what the bot already
does. A rename is only worth it where the legacy name is actively confusing or wrong.

Decision rule suggestion: rename only groups whose name appears in a *person-facing* place (welcome email, repo
list, `onboard crowd teams`), and alias the rest.

## 3. Plan, step by step

1. **Inventory.** Run the discovery above. Produce, per group to be renamed, the list of references (application,
   place, count). Use `onboard crowd teams` for the tree and the Crowd REST API for memberships.
2. **Choose the groups and the target names.** Start from `scripts/suggest_crowd_mapping.py` output: the groups it
   matches to a canonical team with high confidence are the candidates; write the rename table (old → new).
   Do a **pilot** on one small, low-risk group first.
3. **Check the technical prerequisites** (nesting, directory write access, name collisions, case sensitivity:
   Crowd group names are case-insensitive but applications may store the case they first saw).
4. **Bot changes** (later code, see §5): rename support in the tooling, a mapping that can list several Crowd
   groups for a canonical team during the transition (already supported: a list), and a report that shows which
   users are in the old but not in the new group.
5. **Per group, approach B:** create, nest, copy memberships, switch the bot mapping, migrate references,
   verify, retire the old group.
6. **Verify after each step.** For a sample of users per group: can they still log in to each application, can
   they still do what they could (spot-check a permission per application), and are there new "group not found"
   warnings in the application logs (Jira/Confluence/Bitbucket report unresolved groups in their admin health
   checks).
7. **Retire**: delete (or archive by emptying and renaming to `zz-retired-...` if Crowd allows) the old group,
   remove it from `team_mapping.yml`, and refresh the group tree cache (`CrowdApi` caches it).
8. **Communicate**: the welcome email and docs name groups; update them. The bot's own `crowd_users.yml`
   `@group` permissions must be updated before the old group disappears (otherwise users lose chat permissions).

Rollback: until step 7 of approach B, nothing has been removed, so the rollback is to point the mapping back
and stop using the new group.

## 4. What the bot could help with later

(Not now; a possible shape for the future work.)

- `crowd group-members <group>` and a diff command: members of old vs. new group.
- `scripts/rename_crowd_group.py OLD NEW` (preview by default, `--apply`): create the new group, nest it under the
  old, copy the direct members (using `CrowdApi`, which needs write calls for groups; today it mostly reads and
  adds/removes users in groups), and print the reference checklist.
- A **reference finder** for the places we can read ourselves: Bitbucket's permission REST API (the bot already has
  a read-only `bitbucket_api.py` listing repositories by group), Jira/Confluence REST (`/rest/api/2/...`
  permission scheme and space permission endpoints), so the inventory in §3 step 1 is partly automatic. Read-only.
- Update `team_mapping.yml` is a hand edit (the file is private config); the script only prints the line.

## 5. Replacing the special access groups

Today a group such as `erb-ocp-dev-anonymous`, a child of `erb-ocp-anonymous`, exists only to grant a
specific application (Bitbucket; for Confluence, a similar one because of licensing). The question is whether a
Crowd *role* or *attribute* could do that instead.

### What the applications can and cannot read from Crowd

The Atlassian applications get **users, groups and memberships** (plus a few user fields: display name, email,
active flag) from Crowd. They do **not** use custom Crowd user attributes for authorization, and they do not use
Crowd "roles" (**verify**: the roles concept exists only for legacy applications and is not used by Jira,
Confluence, Bitbucket or Bamboo). So an attribute or a role in Crowd cannot be turned into a permission without
code on the application side (a plugin or an authenticator), which is not something to take on for this.

Therefore: **the group is the only permission-bearing primitive**, and the answer to "can we skip them" is *no,
not literally*. What we can do is get rid of the *special-purpose, per-team* groups and the awkward hierarchy.

### Options

| Option | Idea | Pros | Cons |
|---|---|---|---|
| **1. Capability groups, flat** | One small set of groups named for the *capability*: `app-bitbucket-users`, `app-confluence-users`, `app-jira-users`, ... Applications grant licence/login to these groups only. Team groups (`dev-payments`) are used only for team permissions. | Very few special groups (one per application) instead of one per team. Meaning is obvious from the name. Licence counts are one query. | The bot has to put people into both their team group and the capability groups. Every team's repositories must be granted to the team group, not to the `-anonymous` one. |
| **2. Restrict by Crowd application mapping** | In Crowd, each application's directory mapping can limit *which groups may authenticate* to that application. Make "may log in to Bitbucket" = a capability group (option 1), and keep permissions on team groups. | Login/licence control lives in one place (Crowd), not duplicated in each application's permission scheme. Removing someone from the capability group blocks the login. | Applies to authentication only, not to what they can do once in. Configure and test per application (**verify** the exact setting names in your Crowd version). |
| **3. Derived membership** | Don't hand-maintain the special groups: the bot adds a person to the capability groups when a canonical team says they need them (a new column in `team_mapping.yml`, e.g. `crowd.capabilities: [bitbucket]`), and removes them on offboarding/move. | The `-dev-anonymous` hierarchy disappears; one rule per canonical team. | New bot code; the mapping file gets a new concept. |
| **4. Keep as is, only rename** | Leave the special groups; rename/align them using §2. | Nothing new to learn. | Keeps the duplicated hierarchy and the confusing names. |

Recommendation: **1 + 2 (+ 3 when the bot work is scheduled)**.

The Confluence licensing case is the one to look at first: if the group exists so that only some people consume a
Confluence licence, option 2 does exactly that without any per-team group: the capability group is the licence
gate.

Note on the naming: the last part of these groups (`anonymous` in `erb-ocp-dev-anonymous`) is only an example of a
**suffix** that names one set of repositories or one access purpose; it could equally be `xnull`, `insomniacs`,
and so on. The pattern is therefore `<team>-<suffix>` under a `<parent>-<suffix>` group, i.e. one extra group per
team *per access set*, and the suffix carries the meaning (it does not mean "public" access). For the Bitbucket
case the question is what each suffix grants. If a suffix stands for a fixed set of repositories or projects,
the cleaner replacement is one group per access set (`bitbucket-<suffix>`, granted once on those projects) and the
team groups stay plain; a person gets the access-set group through the team's capabilities (option 3), not
through a per-team shadow group. The real permission listing (`bitbucket_api.py` can produce it read-only)
shows which suffixes exist and what each grants, and that decides the option.

### Migration of the special groups (same method as §2)

1. Create the capability groups; nest the *new* groups under the old special groups (approach B) so nobody loses access.
2. Grant the permissions to the capability/team groups in each application, as in §3 step 6.
3. Switch the bot to put people in the capability groups; stop using the old special groups.
4. Remove the old special groups when empty and unreferenced.

## 6. Risks and open questions

- Does **nesting** work in *every* application with the real directory settings? (The pilot answers this.)
- Which Crowd directories are **read-only (delegated to AD)**? Renames there need AD changes and a different
  route.
- **Case**: Crowd group names are case-insensitive, applications may not be (Confluence stores the case it saw).
- **Licensing**: during approach B a person may sit in two groups; make sure that does not count twice.
  Atlassian licences count users, not group memberships, but check the Confluence/Jira licence-use report during the pilot.
- **Page restrictions/saved filters** are the references that are easiest to miss: they are not in any admin
  overview of "where is this group used" (Jira does have "Where is this group used"-style checks in newer
  versions; **verify**).
- Subversion: the Apache/Crowd connector may cache group lookups; restart or wait out the cache after changes.
- The bot's own state: `crowd` provisions store the groups that were granted when the person was onboarded. After a
  rename they list the old name; decide whether to rewrite those rows (a one-off script) or keep them as history.
- What does each suffix (`anonymous`, `xnull`, `insomniacs`, ...) grant, and to which repositories/spaces? That
  decides the option in §5.

## 7. Suggested order of work

1. Discovery and inventory (read-only; no risk).
2. Decide what the special groups do (§5), which also decides how many groups need a rename at all.
3. Pilot approach B on one group.
4. Bot support (rename script, capability mapping), only if the pilot shows it is worth automating.
5. Roll out in batches, one application at a time, with the checklist from the inventory.
