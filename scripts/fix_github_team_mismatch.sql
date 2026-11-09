-- Find accounts whose team differs from the team of their (live) GitHub provision, and optionally fix them.
--
-- The account team is the canonical team (a GitHub enterprise team slug); the provision keeps it as data->>'team'
-- ("ent:<slug>"). They are compared case-insensitively, without the "ent:" prefix. Accounts with no team at all
-- count as a mismatch too. Provisions without a team, and ended ones (expired, deprovisioned, ...), are ignored.
--
-- Usage (report only, changes nothing):
--   psql "$MIGRATIONS_DATABASE_URL" -f scripts/fix_github_team_mismatch.sql
-- Fix, trusting the provision (what GitHub was told): set accounts.team from the provision:
--   psql "$MIGRATIONS_DATABASE_URL" -v fix=provision -f scripts/fix_github_team_mismatch.sql
-- Fix, trusting the account: set the provision's team to 'ent:' || accounts.team (the user is NOT moved on GitHub!):
--   psql "$MIGRATIONS_DATABASE_URL" -v fix=account -f scripts/fix_github_team_mismatch.sql
-- The fix runs in one transaction and prints the rows it changed; account changes are recorded in account_history.

BEGIN;

CREATE TEMP TABLE team_mismatch ON COMMIT DROP AS
SELECT a.id AS account_id, a.primary_email, p.status,
       a.team AS account_team, p.data->>'team' AS provision_team,
       regexp_replace(lower(btrim(p.data->>'team')), '^ent:', '') AS provision_slug
FROM accounts a
JOIN account_provisions p ON p.account_id = a.id AND p.resource = 'github'
WHERE p.status IN ('pending', 'invited', 'accepted', 'assigned', 'active')
  AND nullif(btrim(p.data->>'team'), '') IS NOT NULL
  AND lower(btrim(a.team)) IS DISTINCT FROM regexp_replace(lower(btrim(p.data->>'team')), '^ent:', '');

\echo
\echo '== Accounts whose team differs from their GitHub provision'
SELECT primary_email, status, account_team, provision_team
FROM team_mismatch
ORDER BY lower(primary_email);

\echo
\echo '== Count by (account team -> provision team)'
SELECT coalesce(account_team, '(none)') AS account_team, provision_slug AS provision_team, count(*)
FROM team_mismatch
GROUP BY 1, 2
ORDER BY 3 DESC, 1, 2;

\if :{?fix}
\echo
\echo '== Fixing, trusting :fix'
SELECT :'fix' = 'provision' AS trust_provision, :'fix' = 'account' AS trust_account \gset

\if :trust_provision
WITH changed AS (
    UPDATE accounts a SET team = m.provision_slug, updated_at = now()
    FROM team_mismatch m
    WHERE a.id = m.account_id
    RETURNING a.id, a.name, a.primary_email, a.team, a.metadata
), history AS (
    INSERT INTO account_history (account_id, name, primary_email, team, metadata)
    SELECT id, name, primary_email, team, metadata FROM changed
)
SELECT primary_email, team AS new_team FROM changed ORDER BY lower(primary_email);
\elif :trust_account
UPDATE account_provisions p
SET data = jsonb_set(p.data, '{team}', to_jsonb('ent:' || m.account_team)), updated_at = now()
FROM team_mismatch m
WHERE p.account_id = m.account_id AND p.resource = 'github' AND m.account_team IS NOT NULL
RETURNING m.primary_email, p.data->>'team' AS new_team;
\else
\echo 'fix must be "provision" or "account"; nothing changed.'
\endif
\endif

COMMIT;
