#!/usr/bin/env sh
# Runs the Alembic migrations of an instance as a database user that owns the tables.
# Usage (any directory): deploy/migrate.sh
# Asks (whiptail) which instance to migrate, from the list of .env.d/*.env, then for the database
# user (default: postgres) and its password. The host, port and database come from the instance's
# env file; the password is passed through PGPASSWORD, so it needs no URL escaping, and it only
# lives in this process.
set -eu

cd "$(dirname "$0")/.."

if ! command -v whiptail >/dev/null 2>&1; then
    echo "whiptail is required (apt install whiptail)" >&2
    exit 1
fi

set --
for file in .env.d/*.env; do
    [ -e "$file" ] || continue
    set -- "$@" "$(basename "$file" .env)" ""
done
if [ "$#" -eq 0 ]; then
    echo "No .env.d/*.env files found" >&2
    exit 1
fi
env_name="$(whiptail --title 'Migrate' --menu 'Instance (.env.d)' 20 60 10 "$@" 3>&1 1>&2 2>&3)"

db_user="$(whiptail --title 'PostgreSQL' --inputbox 'Database user (must own the tables)' 10 50 postgres 3>&1 1>&2 2>&3)"
PGPASSWORD="$(whiptail --title 'PostgreSQL' --passwordbox "Password of $db_user" 10 50 3>&1 1>&2 2>&3)"
export PGPASSWORD

# Same connection as the instance, but as db_user and without a password.
MIGRATIONS_DATABASE_URL="$(uv run python deploy/migration_url.py "$env_name" "$db_user")"
export MIGRATIONS_DATABASE_URL

echo "Migrating $MIGRATIONS_DATABASE_URL"
uv run alembic -x "env=$env_name" upgrade head
uv run alembic -x "env=$env_name" check
