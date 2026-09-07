#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrate_permissions.py

One-shot, NON-DESTRUCTIVE migration script that consolidates all the scattered
``config/*.permissions.yml`` files into either a single ``config/permissions.yml``
file and/or a ``permission_rules`` table in Postgres, keyed by the fully-qualified
function name (``func.__module__ + ':' + func.__name__``), with a ``roles``
sub-block per function so a single command can show different results to
different users/channels.

It does NOT touch application code (backend/configuration.py, backend/approval.py
still read the old per-file layout) and does NOT delete/modify any existing
``*.permissions.yml`` file. Re-run it any time; it always regenerates its
output(s) from scratch from the current source files.

Usage:
    python scripts/migrate_permissions.py [--config-dir config] [--out config/permissions.yml]
    python scripts/migrate_permissions.py --to-db [--prune]
    python scripts/migrate_permissions.py --to-db --skip-yaml

``--to-db`` additionally (or, with ``--skip-yaml``, instead) upserts every rule
into the ``permission_rules`` table via ``PERMISSIONS_DATABASE_URL`` (currently
pointed at the same physical database as ``APPROVAL_DATABASE_URL``, just a
separate env var so it can be split out later). ``--prune`` deletes rows for
function names produced by this run whose (environment, role) combo no longer
appears in the source YAML - use with care.

After reviewing/adjusting the generated output, wiring it up requires updating
``check_security`` / ``check_approval_security`` to read from it (out of scope
for this script, by design).
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

from ruamel.yaml import YAML

yaml = YAML()
yaml.default_flow_style = False
yaml.width = 4096  # avoid line-wrapping long user/channel lists

# Sentinel used for the `environment` column/key when a function has no
# per-environment axis (approval-queue style commands). Deliberately NOT NULL
# so the DB's UNIQUE(function_name, environment, role) constraint behaves
# predictably on upsert - Postgres treats NULL <> NULL, so ON CONFLICT would
# never match a NULL environment and every re-run would insert duplicates.
GLOBAL_ENVIRONMENT = ''


# --------------------------------------------------------------------------
# Mapping of legacy "check_security"-style permission files to the click
# commands they actually gate. Built by inspecting every @check_security use
# in commands/openshift/*.py against the config env var each module reads
# (OPENSHIFT_DEPLOYMENT -> deployment.yml -> deployment.permissions.yml, etc).
#
# `sources` lists the permission-file stems that feed this function. When a
# function has more than one source (e.g. `mock` is fed by both mock.yml and
# mock-oc.yml, which are alternate configs for different physical bot
# instances but reuse the same environment labels like "dev"/"qa"), each
# source's environment keys are prefixed with "<stem>-" to avoid silently
# overwriting one config's "dev" with another's. Single-source functions keep
# their original environment names for readability.
# --------------------------------------------------------------------------
CHECK_SECURITY_FUNCTIONS = {
    'commands.openshift.deployment:list_deployments': ['deployment'],
    'commands.openshift.deployment:pause_deployment': ['deployment'],
    'commands.openshift.deployment:resume_deployment': ['deployment'],

    'commands.openshift.cronjob:list_cronjobs': ['cronjob'],
    'commands.openshift.cronjob:pause_cronjob': ['cronjob'],
    'commands.openshift.cronjob:resume_cronjob': ['cronjob'],
    'commands.openshift.cronjob:disable': ['cronjob'],
    'commands.openshift.cronjob:enable': ['cronjob'],

    'commands.openshift.scaledown:scaledown_do': ['scaledown'],

    'commands.openshift.refresh_actuator:refresh_actuator': ['actuator_refresh'],
    'commands.openshift.refresh_actuator:view_actuator': ['actuator_refresh'],
    'commands.openshift.refresh_actuator:health_actuator': ['actuator_refresh'],
    'commands.openshift.refresh_actuator:pods': ['actuator_refresh'],

    # mock-oc.yml is for a different Slack workspace and is intentionally
    # excluded here (see also SKIPPED_SOURCES below).
    'commands.openshift.mock:set_mock': ['mock'],
    'commands.openshift.mock:mock_check': ['mock'],
    'commands.openshift.mock:mock_view': ['mock'],

    # `deploy` currently has NO @check_security applied (the command body is a
    # stub that returns immediately). Its permission files
    # (docker-deploy.oc3/oc4.permissions.yml) are intentionally excluded (see
    # SKIPPED_SOURCES below) - one is empty, the other contains corrupted
    # non-YAML content, and neither is enforced in code today.
}

# Source-file stems that are intentionally excluded from migration (per user
# request), even though they exist under config/. Listed here purely so the
# report below can note *why* a function has no entries, rather than silently
# omitting them.
SKIPPED_SOURCES = {
    'mock-oc': 'different Slack workspace - not part of this bot instance\'s permission set',
    'docker-deploy.oc3': 'excluded - deploy command has no @check_security applied today',
    'docker-deploy.oc4': 'excluded - deploy command has no @check_security applied today',
}

# Approval-queue functions (backend/approval.py `requires_approval`). Unlike
# the table above these have no per-environment/namespace axis - they use
# `roles: requester / approver` directly. `notify_channel`/`environment`/
# `allow_self` come from approvals.yml + approvals.permissions.yml.
APPROVAL_FUNCTIONS = [
    'commands.onboarding:onboard_slack',
    'commands.onboarding:offboard',
    'commands.onboarding.crowd:onboard_crowd',
    'commands.onboarding.jetbrains:onboard_jetbrains',
    'commands.onboarding.github:onboard_github',
]

# Must match backend.approval.GLOBAL_APPROVAL_FUNCTION - sentinel row gating
# the approval queue's own commands (list/show/approve/reject), as opposed to
# any single approval-gated command.
GLOBAL_APPROVAL_FUNCTION = 'backend.approval:_global'

# Admin-curated rules with no legacy YAML source - new commands introduced
# alongside the DB-backed permission system itself (commands/permissions.py).
# Environment '' (GLOBAL_ENVIRONMENT) + role 'default', matching
# backend.configuration.check_security's lookup for commands with no
# `namespace` argument. Adjust the user/channel lists as needed; there is no
# YAML source of truth for these, so re-running the migration will NOT pick up
# manual DB edits made directly to these two rows - edit BOOTSTRAP_FUNCTIONS
# instead and re-run.
BOOTSTRAP_FUNCTIONS = {
    'commands.permissions:reload_permissions': {
        'environments': {
            '': {
                'roles': {
                    'default': {
                        # TODO: replace with real admin Slack user ID(s)/@group before running --to-db
                        'users': ['<REPLACE_WITH_ADMIN_USER_ID>'],
                        'channels': ['*'],
                    }
                }
            }
        }
    },
    'commands.permissions:show_permission': {
        'environments': {
            '': {
                'roles': {
                    'default': {
                        # TODO: replace with real admin Slack user ID(s)/@group before running --to-db
                        'users': ['<REPLACE_WITH_ADMIN_USER_ID>'],
                        'channels': ['*'],
                    }
                }
            }
        }
    },
}


def load_yaml(path: pathlib.Path, warnings: list | None = None):
    if not path.exists():
        return None
    try:
        with path.open(encoding='utf8') as f:
            return yaml.load(f)
    except Exception as ex:  # malformed/unexpected content - don't abort the whole migration
        if warnings is not None:
            warnings.append(f"[unparseable] {path}: {ex.__class__.__name__}: {ex} - skipped")
        return None


def migrate_check_security(config_dir: pathlib.Path, result: dict, warnings: list):
    for func_name, sources in CHECK_SECURITY_FUNCTIONS.items():
        merged_envs: dict = {}
        for stem in sources:
            perm_file = config_dir / f'{stem}.permissions.yml'
            if not perm_file.exists():
                warnings.append(f"[missing] {perm_file} referenced by {func_name} but not found")
                continue
            data = load_yaml(perm_file, warnings)
            if not data:
                warnings.append(f"[empty] {perm_file} referenced by {func_name} is empty/unparseable - skipped")
                continue
            for env_name, env_perms in data.items():
                if env_name in merged_envs:
                    warnings.append(
                        f"[collision] {func_name}: environment key '{env_name}' "
                        f"already populated (from another source?) - overwriting")
                merged_envs[env_name] = {
                    'roles': {
                        'default': {
                            'users': env_perms.get('users', []),
                            'channels': env_perms.get('channels', []),
                        }
                    }
                }
        result[func_name] = {'environments': merged_envs}


def migrate_approvals(config_dir: pathlib.Path, result: dict, warnings: list):
    core = load_yaml(config_dir / 'approvals.yml', warnings) or {}
    permissions = load_yaml(config_dir / 'approvals.permissions.yml', warnings) or {}

    environment = core.get('environment')
    if environment is None:
        if len(permissions) == 1:
            environment = next(iter(permissions))
        else:
            warnings.append("[error] approvals.yml has no `environment:` and "
                             "approvals.permissions.yml defines more than one - skipping approvals migration")
            return
    env_perms = permissions.get(environment) or {}

    requesters = env_perms.get('requesters', [])
    approvers = env_perms.get('approvers', [])
    approve_channels = env_perms.get('approve_channels', [])
    notify_channel = env_perms.get('notify_channel')
    request_channels_cfg = env_perms.get('request_channels', {})

    default_request_channels = ['*']
    per_function_channels: dict = {}
    if isinstance(request_channels_cfg, dict):
        default_request_channels = request_channels_cfg.get('*', ['*'])
        for key, chans in request_channels_cfg.items():
            if key == '*':
                continue
            per_function_channels[key] = chans
    elif isinstance(request_channels_cfg, list):
        default_request_channels = request_channels_cfg

    # Known existing bug: approvals.permissions.yml overrides
    # 'commands.onboarding.github:onboard_jetbrains' but onboard_jetbrains
    # actually lives in commands.onboarding.jetbrains, not .github. Flag it and
    # migrate BOTH the (likely intended) corrected key and the original
    # verbatim key so nothing is silently dropped/renamed without review.
    for stale_key in list(per_function_channels):
        if stale_key not in APPROVAL_FUNCTIONS and stale_key not in CHECK_SECURITY_FUNCTIONS:
            warnings.append(
                f"[review] approvals.permissions.yml request_channels has key "
                f"'{stale_key}' which doesn't match any known function full name "
                f"- likely a stale/typo'd override (e.g. wrong module path); "
                f"carried over as-is, please fix manually")

    for func_name in APPROVAL_FUNCTIONS:
        channels = per_function_channels.get(func_name, default_request_channels)
        result[func_name] = {
            'roles': {
                'requester': {
                    'users': requesters,
                    'channels': channels,
                },
                'approver': {
                    'users': approvers,
                    'channels': approve_channels,
                },
            },
            'notify_channel': notify_channel,
            'meta': {
                'environment': environment,
                'allow_self': core.get('allow_self', False),
            },
        }

    # Sentinel row gating the approval queue's *own* commands
    # (commands/approvals.py: list/show/approve/reject) - these operate the
    # whole queue, not any single approval-gated command, so
    # backend.approval.check_approval_security resolves against this fixed
    # name (backend.approval.GLOBAL_APPROVAL_FUNCTION) rather than its own
    # module:function name.
    result[GLOBAL_APPROVAL_FUNCTION] = {
        'roles': {
            'requester': {
                'users': requesters,
                'channels': default_request_channels,
            },
            'approver': {
                'users': approvers,
                'channels': approve_channels,
            },
        },
        'notify_channel': notify_channel,
        'meta': {
            'environment': environment,
            'allow_self': core.get('allow_self', False),
        },
    }

    # Also carry over any stale/typo'd override verbatim so a human can decide
    # whether to fix the source function or delete the dead entry.
    for stale_key, chans in per_function_channels.items():
        if stale_key not in APPROVAL_FUNCTIONS:
            result.setdefault(stale_key, {
                'roles': {
                    'requester': {'users': requesters, 'channels': chans},
                    'approver': {'users': approvers, 'channels': approve_channels},
                },
                'notify_channel': notify_channel,
                'meta': {'environment': environment, 'allow_self': core.get('allow_self', False)},
            })


def add_bootstrap_functions(result: dict):
    """Admin-curated rules with no legacy YAML source: new commands introduced
    alongside the DB-backed permission system itself. Regenerated every run so
    they're never accidentally dropped; edit BOOTSTRAP_FUNCTIONS to change who
    may use them."""
    for func_name, entry in BOOTSTRAP_FUNCTIONS.items():
        result[func_name] = entry


def check_bootstrap_placeholders(warnings: list):
    for func_name, entry in BOOTSTRAP_FUNCTIONS.items():
        flat = str(entry)
        if '<REPLACE_WITH_ADMIN_USER_ID>' in flat:
            warnings.append(
                f"[review] {func_name}: BOOTSTRAP_FUNCTIONS still has the "
                f"placeholder admin user ID - edit scripts/migrate_permissions.py "
                f"before running --to-db against a real environment")


def flatten_to_rows(ordered: dict) -> list[dict]:
    """Flatten the nested YAML-shaped dict into rows matching `permission_rules`.

    - Check-security style entries (`environments.<env>.roles.<role>.{users,channels}`)
      produce one row per (function, environment, role).
    - Approval style entries (`roles.<role>.{users,channels}`, no `environments` key)
      produce one row per (function, GLOBAL_ENVIRONMENT, role), carrying
      `notify_channel`/`meta` into the `extra` column.
    """
    rows = []
    for func_name, entry in ordered.items():
        if 'environments' in entry:
            for env_name, env_entry in entry['environments'].items():
                for role_name, role_perms in (env_entry.get('roles') or {}).items():
                    rows.append({
                        'function_name': func_name,
                        'environment': env_name,
                        'role': role_name,
                        'users': role_perms.get('users', []),
                        'channels': role_perms.get('channels', []),
                        'extra': {},
                    })
        elif 'roles' in entry:
            extra = {}
            if entry.get('notify_channel') is not None:
                extra['notify_channel'] = entry['notify_channel']
            if entry.get('meta') is not None:
                extra['meta'] = entry['meta']
            for role_name, role_perms in entry['roles'].items():
                rows.append({
                    'function_name': func_name,
                    'environment': GLOBAL_ENVIRONMENT,
                    'role': role_name,
                    'users': role_perms.get('users', []),
                    'channels': role_perms.get('channels', []),
                    'extra': extra,
                })
    return rows


_PERMISSION_RULES_SCHEMA = """
CREATE TABLE IF NOT EXISTS permission_rules (
    id            SERIAL PRIMARY KEY,
    function_name TEXT NOT NULL,
    environment   TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'default',
    users         JSONB NOT NULL DEFAULT '[]'::jsonb,
    channels      JSONB NOT NULL DEFAULT '[]'::jsonb,
    extra         JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (function_name, environment, role)
);
"""


def write_to_db(rows: list[dict], warnings: list, prune: bool = False) -> int:
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError:
        warnings.append("[error] psycopg is not installed - cannot write to DB")
        return 0

    dsn = os.environ.get('PERMISSIONS_DATABASE_URL')
    if not dsn:
        warnings.append("[error] PERMISSIONS_DATABASE_URL not set - skipping DB write")
        return 0

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_PERMISSION_RULES_SCHEMA)
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO permission_rules
                        (function_name, environment, role, users, channels, extra)
                    VALUES
                        (%(function_name)s, %(environment)s, %(role)s,
                         %(users)s, %(channels)s, %(extra)s)
                    ON CONFLICT (function_name, environment, role)
                    DO UPDATE SET
                        users = EXCLUDED.users,
                        channels = EXCLUDED.channels,
                        extra = EXCLUDED.extra,
                        updated_at = NOW();
                    """,
                    {
                        'function_name': row['function_name'],
                        'environment': row['environment'],
                        'role': row['role'],
                        'users': Jsonb(row['users']),
                        'channels': Jsonb(row['channels']),
                        'extra': Jsonb(row['extra']),
                    })

            if prune:
                by_function: dict[str, set] = {}
                for row in rows:
                    by_function.setdefault(row['function_name'], set()).add(
                        (row['environment'], row['role']))
                for function_name, keep in by_function.items():
                    cur.execute(
                        "SELECT environment, role FROM permission_rules WHERE function_name = %s;",
                        (function_name,))
                    stale = [(env, role) for (env, role) in cur.fetchall() if (env, role) not in keep]
                    for env, role in stale:
                        cur.execute(
                            "DELETE FROM permission_rules "
                            "WHERE function_name = %s AND environment = %s AND role = %s;",
                            (function_name, env, role))
                        warnings.append(
                            f"[pruned] {function_name} environment={env!r} role={role!r} "
                            f"- no longer present in source YAML")
        conn.commit()
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', default='config', type=pathlib.Path)
    parser.add_argument('--out', default=None, type=pathlib.Path)
    parser.add_argument('--to-db', action='store_true',
                        help="Also (or, with --skip-yaml, instead) upsert rules into "
                             "permission_rules via PERMISSIONS_DATABASE_URL")
    parser.add_argument('--skip-yaml', action='store_true',
                        help="Don't write the config/permissions.yml file (use with --to-db)")
    parser.add_argument('--prune', action='store_true',
                        help="With --to-db, delete DB rows for migrated functions whose "
                             "(environment, role) no longer appears in the source YAML")
    args = parser.parse_args()

    config_dir: pathlib.Path = args.config_dir
    out_path: pathlib.Path = args.out or (config_dir / 'permissions.yml')

    if not config_dir.exists():
        print(f"Config dir {config_dir} does not exist", file=sys.stderr)
        return 1

    result: dict = {}
    warnings: list = []

    for stem, reason in SKIPPED_SOURCES.items():
        warnings.append(f"[skipped] {config_dir / (stem + '.permissions.yml')}: {reason}")

    migrate_check_security(config_dir, result, warnings)
    migrate_approvals(config_dir, result, warnings)
    add_bootstrap_functions(result)
    check_bootstrap_placeholders(warnings)

    # Sort for a stable, readable diff-friendly output.
    ordered = {k: result[k] for k in sorted(result)}

    header = (
        "# Auto-generated by scripts/migrate_permissions.py - DO NOT HAND-EDIT the\n"
        "# structure lightly; regenerating will overwrite this file.\n"
        "#\n"
        "# Keyed by fully-qualified function name (func.__module__:func.__name__).\n"
        "# - Commands gated with @check_security (OpenShift/K8s style) nest under\n"
        "#   `environments.<env>.roles.<role>.{users,channels}`. Only a `default`\n"
        "#   role is populated today; add more roles per environment to show\n"
        "#   different results to different users/channels for the same command.\n"
        "# - Commands gated with @requires_approval (backend/approval.py) have no\n"
        "#   `environments` axis; they nest directly under\n"
        "#   `roles.<requester|approver>.{users,channels}`, plus `notify_channel`\n"
        "#   and `meta.{environment,allow_self}` carried over from approvals.yml.\n"
        "#\n"
        "# This file was generated from the legacy config/*.permissions.yml files,\n"
        "# which have NOT been deleted or modified. See the migration report\n"
        "# printed by the script for collisions/orphans that need manual review.\n"
    )

    if not args.skip_yaml:
        with out_path.open('w', encoding='utf8') as f:
            f.write(header)
            yaml.dump(ordered, f)
        print(f"Wrote {out_path} with {len(ordered)} function entries.")

    if args.to_db:
        rows = flatten_to_rows(ordered)
        written = write_to_db(rows, warnings, prune=args.prune)
        if written:
            print(f"Upserted {written} row(s) into permission_rules "
                  f"via PERMISSIONS_DATABASE_URL.")

    print()
    if warnings:
        print(f"{len(warnings)} item(s) need manual review:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("No warnings.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
