-- Show the GitHub provision history of one or more accounts, to check which dates are trustworthy.
--
-- Usage (emails separated by commas, no spaces, in a Postgres array literal):
--   psql "$MIGRATIONS_DATABASE_URL" -v emails='{jdoe@example.com,asmith@example.com}' -f scripts/provision_history.sql
-- Optionally pass -v resource=jetbrains to look at another resource (default: github).

\if :{?resource}
\else
\set resource github
\endif

\echo
\echo '== Current provision row (created_at is when the row was last (re)written as new, updated_at the last change)'
SELECT a.primary_email, p.status, p.created_at, p.updated_at,
       p.data->>'username' AS username, p.data->>'expired_at' AS data_expired_at
FROM accounts a
JOIN account_provisions p ON p.account_id = a.id AND p.resource = :'resource'
WHERE lower(a.primary_email) = ANY (SELECT lower(e) FROM unnest(:'emails'::text[]) AS e)
ORDER BY a.primary_email;

\echo
\echo '== Full history, oldest first'
SELECT a.primary_email, h.recorded_at, h.previous_status, h.status
FROM accounts a
JOIN account_provision_history h ON h.account_id = a.id AND h.resource = :'resource'
WHERE lower(a.primary_email) = ANY (SELECT lower(e) FROM unnest(:'emails'::text[]) AS e)
ORDER BY a.primary_email, h.recorded_at, h.id;

\echo
\echo '== What the "expired" command would show from history: first invited vs. first expired'
SELECT a.primary_email,
       min(h.recorded_at) FILTER (WHERE h.status = 'invited') AS first_invited,
       max(h.recorded_at) FILTER (WHERE h.status = 'invited') AS last_invited,
       max(h.recorded_at) FILTER (WHERE h.status = 'expired') AS last_expired
FROM accounts a
JOIN account_provision_history h ON h.account_id = a.id AND h.resource = :'resource'
WHERE lower(a.primary_email) = ANY (SELECT lower(e) FROM unnest(:'emails'::text[]) AS e)
GROUP BY a.primary_email
ORDER BY a.primary_email;
