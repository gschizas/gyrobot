#!/usr/bin/env python3
"""Record the JetBrains licences that already exist in the JetBrains account as provisions.

Licences assigned before the bot managed JetBrains have no provision, so ``offboard`` and ``onboard move`` cannot
see them. Usage (from the repository root; reads the database and JetBrains settings from .env.d/<env-name>.env):

    uv run python scripts/backfill_jetbrains.py <env-name>           # preview only
    uv run python scripts/backfill_jetbrains.py <env-name> --apply   # write to the database

For every IntelliJ IDEA licence assigned to a person (not to a licence server or key) the script creates an
``active`` jetbrains provision holding the email, JetBrains team and licence id, marked ``imported: true``;
the account is created when the email is unknown. Existing live provisions are only completed with a missing
licence/team id. A person with a deprovisioned (or otherwise not live) provision is reported and left untouched,
and so is a person holding several licences (the first is recorded). JetBrains does not say when a licence was
assigned, so the import date is used.

Emails outside ``allowed_email_domains`` (see ``backend/email_domains.py``) never get an account of their own.
Such a licence is attached to an existing account when its email is already one of that account's
``additional_emails``, or when --map names the account:

    uv run python scripts/backfill_jetbrains.py <env-name> --map mapping.csv

where mapping.csv has the header ``external_email,account_email``. The external email is then recorded as an
additional email of that account (so the provision keeps the address JetBrains knows). Otherwise the licence is
skipped, and the preview suggests accounts whose name equals the licence holder's name as lines ready to paste
into the mapping file; suggestions are never applied automatically.

Two helpers create the mapping files to fill in by hand (they refuse to overwrite an existing file):

    --write-email-map FILE   CSV of the outside-domain emails still unmapped: external_email,account_email (blank, to
                             fill in), holder_name, candidates (accounts with the same name, for reference only).
                             Rows with a blank account_email are ignored when the file is passed back through --map.
    --write-team-map FILE    YAML ``jetbrains:`` section with one placeholder entry per JetBrains team that no core
                             team maps to yet. Replace each placeholder key with a core team (add more lines for
                             further core teams of the same JetBrains team) and merge it into
                             config/team_mapping.yml.
    --report-misplaced CSV   Lists holders whose core team maps (via team_mapping.yml, parents included) to a
                             different JetBrains team than the one they hold a licence in, plus the core teams that
                             have no jetbrains mapping (cannot judge). Also written to a new CSV. Report only.
"""
import argparse
import csv
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from dotenv import load_dotenv


def read_mapping(path: str) -> dict[str, str]:
    with open(path, newline='', encoding='utf8') as f:
        reader = csv.DictReader(f)
        if not {'external_email', 'account_email'} <= set(reader.fieldnames or []):
            sys.exit(f"{path}: the header must be external_email,account_email")
        return {row['external_email'].strip().lower(): row['account_email'].strip()
                for row in reader if row['external_email'].strip() and row['account_email'].strip()}


def write_email_map(path: str, unmapped: list[tuple[str, str, list[str]]]) -> None:
    try:
        with open(path, 'x', newline='', encoding='utf8') as f:
            writer = csv.writer(f)
            writer.writerow(['external_email', 'account_email', 'holder_name', 'candidates'])
            for email, name, candidates in unmapped:
                writer.writerow([email, '', name, ';'.join(candidates)])
    except FileExistsError:
        sys.exit(f"{path} already exists; delete it first so a filled-in file is never overwritten")
    print(f"wrote {len(unmapped)} unmapped email(s) to {path}")


def write_team_map(path: str, teams: list, hints: dict) -> None:
    try:
        with open(path, 'x', encoding='utf8') as f:
            f.write("# Replace each FILL-IN key with a core team (it also covers the teams below it), then merge into\n"
                    "# config/team_mapping.yml. Several core teams may point to the same JetBrains team.\njetbrains:\n")
            for team in teams:
                known = ', '.join(f"{core} ({n})" for core, n in hints.get(team.id, Counter()).most_common())
                f.write(f"  # {team.name}: id {team.id}, {team.total_licenses} licences, {team.unassigned_licenses} free"
                        f"{'; core teams of its known holders: ' + known if known else ''}\n")
                f.write(f"  {json.dumps(f'FILL-IN-{team.id}')}: {json.dumps(team.name)}\n")
    except FileExistsError:
        sys.exit(f"{path} already exists; delete it first so a filled-in file is never overwritten")
    print(f"wrote {len(teams)} unmapped JetBrains team(s) to {path}")


def report_misplaced(path: str, misplaced: list, cannot_judge: list) -> None:
    print(f"\n{len(misplaced)} holder(s) in a JetBrains team other than the one their core team maps to:")
    for email, core, actual, expected in sorted(misplaced, key=lambda m: (m[2], m[1], m[0])):
        print(f"  {email:40} core team {core}: holds a licence in {actual}, expected {expected}")
    if cannot_judge:
        print(f"\n{len(cannot_judge)} holder(s) whose core team has no jetbrains mapping (cannot judge):")
        for core, count in Counter(c[1] for c in cannot_judge).most_common():
            print(f"  {core}: {count}")
    try:
        with open(path, 'x', newline='', encoding='utf8') as f:
            writer = csv.writer(f)
            writer.writerow(['status', 'email', 'core_team', 'jetbrains_team', 'expected_jetbrains_team'])
            for email, core, actual, expected in misplaced:
                writer.writerow(['misplaced', email, core, actual, expected])
            for email, core, actual in cannot_judge:
                writer.writerow(['cannot_judge', email, core, actual, ''])
    except FileExistsError:
        sys.exit(f"{path} already exists; delete it first")
    print(f"wrote {len(misplaced) + len(cannot_judge)} row(s) to {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('env_name')
    parser.add_argument('--apply', action='store_true', help='write to the database (default: preview only)')
    parser.add_argument('--map', metavar='CSV', help='external_email,account_email pairs for licences held by '
                                                      'emails outside the allowed domains')
    parser.add_argument('--write-email-map', metavar='FILE', help='write the still unmapped outside-domain emails to a new CSV')
    parser.add_argument('--write-team-map', metavar='FILE', help='write the JetBrains teams no core team maps to, to a new YAML')
    parser.add_argument('--report-misplaced', metavar='CSV', help='list holders whose core team maps to a different '
                                                                   'JetBrains team than the one they hold a licence in; also writes a new CSV')
    args = parser.parse_args()
    for target in (args.write_email_map, args.write_team_map, args.report_misplaced):
        if target and pathlib.Path(target).exists():
            sys.exit(f"{target} already exists; delete it first so a filled-in file is never overwritten")

    load_dotenv(dotenv_path=f'.env.d/{args.env_name}.env', override=True)
    from backend import account_storage as storage
    from backend.email_domains import allowed_email_domains, is_allowed_email
    from backend.jetbrains_api import JetBrainsApi
    from backend.team_mapping import mapped_teams, resolve_team

    mapping = read_mapping(args.map) if args.map else {}
    domains = allowed_email_domains()
    if not domains:
        print("note: no allowed_email_domains configured, every email is treated as internal\n")

    by_email: dict[str, list[dict]] = {}
    skipped_holders = 0
    for lic in JetBrainsApi().get_licenses(assigned=True):
        assignee = lic.get('assignee') or {}
        if assignee.get('type') != 'USER' or not assignee.get('email'):
            skipped_holders += 1
            continue
        by_email.setdefault(assignee['email'].strip().lower(), []).append(lic)

    counts = {'create': 0, 'complete': 0, 'already': 0, 'not live': 0, 'link': 0, 'external': 0, 'duplicate': 0}
    seen: dict = {}  # account id -> the email whose licence was handled in this run (one provision per account)
    unmapped_users: list[tuple[str, str, list[str]]] = []
    team_hints: dict = {}  # JetBrains team id -> Counter of the core teams of its known holders
    jetbrains_teams = JetBrainsApi().get_teams()
    team_identifiers = {t.id: {t.name.lower(), str(t.id), t.slug} for t in jetbrains_teams}
    misplaced: list[tuple[str, str, str, str]] = []  # email, core team, JetBrains team, expected team
    cannot_judge: list[tuple[str, str, str]] = []  # core team has no jetbrains mapping
    for email, licenses in sorted(by_email.items()):
        lic = licenses[0]
        holder_name = (lic.get('assignee') or {}).get('name') or ''
        data = {'email': email, 'team_name': lic['team']['name'], 'team_id': lic['team']['id'],
                'license_id': lic['licenseId'], 'imported': True}
        note = f" (+{len(licenses) - 1} more licence(s) not recorded)" if len(licenses) > 1 else ''

        account = storage.find_account_by_any_email(email)
        link_to = None
        if not account and not is_allowed_email(email, domains):
            target_email = mapping.get(email)
            if target_email:
                account = storage.find_account_by_any_email(target_email)
                if not account:
                    print(f"{'external':10} {email:40} mapped to {target_email}, which is not an account; skipped{note}")
                    counts['external'] += 1
                    continue
                link_to = account
            else:
                print(f"{'external':10} {email:40} outside the allowed domains and not mapped; skipped{note}")
                candidates = [c.primary_email for c in storage.find_accounts_by_name(holder_name)] if holder_name else []
                for candidate in candidates:
                    print(f"{'':10} suggestion: {email},{candidate}   (name \"{holder_name}\")")
                unmapped_users.append((email, holder_name, candidates))
                counts['external'] += 1
                continue

        if account and account.team:
            team_hints.setdefault(lic['team']['id'], Counter())[account.team] += 1
            expected = resolve_team('jetbrains', account.team)
            if expected is None:
                cannot_judge.append((account.primary_email, account.team, lic['team']['name']))
            elif expected.strip().lower() not in team_identifiers.get(lic['team']['id'], {str(lic['team']['id'])}):
                misplaced.append((account.primary_email, account.team, lic['team']['name'], expected))
        existing = storage.get_provision(account.id, 'jetbrains') if account else None
        holder = seen.get(account.id) if account else None
        if holder is None and existing and existing.status in storage.LIVE_STATUSES:
            holder = (existing.data.get('email') or email).lower()
        if holder and holder != email:
            print(f"{'duplicate':10} {email:40} {account.primary_email} already holds a licence as {holder}; skipped")
            counts['duplicate'] += 1
            continue
        if account:
            seen[account.id] = email

        if link_to:
            print(f"{'link' if args.apply else 'would link':14} {email:40} additional email of {link_to.primary_email}")
            if args.apply:
                storage.add_additional_email(link_to.id, email)
            counts['link'] += 1

        if existing and existing.status not in storage.LIVE_STATUSES:
            print(f"{'not live':10} {email:40} provision is {existing.status}, licence {lic['licenseId']} is still assigned")
            counts['not live'] += 1
            continue
        if existing:
            missing = {k: v for k, v in data.items() if k != 'imported' and not existing.data.get(k)}
            if not missing:
                counts['already'] += 1
                continue
            print(f"{'complete' if args.apply else 'would complete':14} {email:40} {', '.join(missing)}{note}")
            if args.apply:
                storage.merge_provision_data(existing.account_id, 'jetbrains', missing)
            counts['complete'] += 1
            continue

        print(f"{'create' if args.apply else 'would create':14} {email:40} {lic['team']['name']}{note}"
              f"{'' if account else ' (new account)'}")
        if args.apply:
            if not account:
                account = storage.create_account(name=holder_name or email, primary_email=email)
            storage.set_provision_status(account.id, 'jetbrains', 'active', data)
        counts['create'] += 1

    print(f"\n{counts['create']} {'created' if args.apply else 'to create'}, "
          f"{counts['complete']} {'completed' if args.apply else 'to complete'}, "
          f"{counts['link']} {'linked' if args.apply else 'to link'}, {counts['already']} already complete, "
          f"{counts['not live']} not live, {counts['external']} external and skipped, "
          f"{counts['duplicate']} duplicate, "
          f"{skipped_holders} not held by a person"
          + ('' if args.apply else "  -- preview only, rerun with --apply to write"))

    mapped_values = {v.strip().lower() for v in mapped_teams('jetbrains')}
    unmapped_teams = [t for t in jetbrains_teams
                      if not mapped_values & {t.name.lower(), str(t.id), t.slug}]
    if unmapped_teams:
        print(f"\n{len(unmapped_teams)} JetBrains team(s) without a core team in config/team_mapping.yml:")
        for team in unmapped_teams:
            print(f"  {team.name} (id {team.id}, {team.total_licenses} licences)")
    if args.write_team_map:
        write_team_map(args.write_team_map, unmapped_teams, team_hints)
    if args.write_email_map:
        write_email_map(args.write_email_map, unmapped_users)
    if args.report_misplaced:
        report_misplaced(args.report_misplaced, misplaced, cannot_judge)


if __name__ == '__main__':
    main()
