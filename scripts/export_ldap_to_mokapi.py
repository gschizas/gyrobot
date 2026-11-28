"""Copy people from the production Active Directory into an LDIF file that Mokapi can serve.

Read-only: it binds with the production credentials (``LDAP_BIND_USERNAME`` / ``LDAP_BIND_PASSWORD``, server and search
base from the Crowd config of the environment) and only searches. Entries keep their real distinguished names and the
attributes the bot reads (names, login, mail, the Greek name, manager, account flags), so the mock behaves like
production. Binary and operational attributes (objectGUID, objectSid, password hashes, ...) are never requested.

The result is personal data: it refuses to write anywhere git does not ignore (use ``config/``), and an existing
file is only replaced with --force. Entries have no ``userPassword``, so Mokapi accepts any password for them.

Pick who to copy with --login (repeatable), --logins-file (one per line), or --filter (an LDAP filter, for example
``(department=Engineering*)``). --with-managers also copies the managers of everyone selected, up to the top, so
``manager`` values resolve.

Run from the repo root (it uses the project environment, since it imports the bot's backend):

    uv run scripts/export_ldap_to_mokapi.py <env-name> --login jdoe --login asmith --with-managers
    uv run scripts/export_ldap_to_mokapi.py <env-name> --filter "(mail=*@example.com)" --limit 300 -o config/ldap-prod.ldif

Then list the file under ``files:`` of your own Mokapi configuration (a copy of ``dev/ldap/ldap.yml`` in ``config/``)
and set the search base and mail domain of the Crowd settings to the production ones.
"""
import pathlib
import subprocess
import sys

import click
from tqdm import tqdm

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'src'))

from backend.cli import gyrobot_env  # noqa: E402

BASE_ATTRIBUTES = ['objectClass', 'cn', 'name', 'sAMAccountName', 'userPrincipalName', 'mail', 'givenName', 'sn',
                   'displayName', 'manager', 'userAccountControl']
MAX_MANAGER_LEVELS = 15


def is_git_ignored(path: pathlib.Path) -> bool:
    """Whether git ignores ``path`` (False when git cannot tell, so the script errs on the side of refusing)."""
    try:
        result = subprocess.run(['git', 'check-ignore', '-q', str(path)], cwd=path.parent, check=False)
    except OSError:
        return False
    return result.returncode == 0


def login_filter(logins: list[str]) -> str:
    from ldap3.utils.conv import escape_filter_chars
    terms = ''.join(f"(sAMAccountName={escape_filter_chars(login)})" for login in logins)
    return f"(&(objectclass=person)(|{terms}))"


def read_logins(path: pathlib.Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


@click.command()
@click.option('--login', 'logins', multiple=True, help='Login (sAMAccountName) to copy; repeatable.')
@click.option('--logins-file', type=click.Path(exists=True, dir_okay=False, path_type=pathlib.Path),
              help='File with one login per line (# comments allowed).')
@click.option('--filter', 'ldap_filter', help='LDAP filter selecting the people to copy.')
@click.option('--limit', default=200, show_default=True, help='Most entries to copy through --filter.')
@click.option('--with-managers', is_flag=True, help='Also copy the managers of everyone selected, up to the top.')
@click.option('-o', '--output', type=click.Path(dir_okay=False, path_type=pathlib.Path),
              default=pathlib.Path('config/ldap-production.ldif'), show_default=True)
@click.option('--force', is_flag=True, help='Replace the output file if it exists.')
@gyrobot_env
def main(logins, logins_file, ldap_filter, limit, with_managers, output, force):
    from backend.ldap_directory import LdapDirectory

    logins = [*logins, *(read_logins(logins_file) if logins_file else [])]
    if not logins and not ldap_filter:
        raise click.UsageError('Choose people with --login, --logins-file or --filter.')
    output = output.resolve()
    if output.exists() and not force:
        raise click.ClickException(f"{output} already exists (use --force to replace it).")
    output.parent.mkdir(parents=True, exist_ok=True)
    if not is_git_ignored(output):
        raise click.ClickException(f"{output} is not ignored by git; the file holds personal data. Use config/.")

    directory = LdapDirectory()
    settings = directory.settings.ldap
    attributes = BASE_ATTRIBUTES + ([settings.greek_name_attribute] if settings.greek_name_attribute else [])
    connection = directory.connection
    entries: dict[str, dict] = {}

    def collect(search_filter: str, base: str, scope, desc: str, max_entries: int | None = None) -> None:
        results = connection.extend.standard.paged_search(
            base, search_filter, search_scope=scope, attributes=attributes, paged_size=500, generator=True)
        for item in tqdm(results, desc=desc, unit='entry', total=max_entries):
            if item.get('type') != 'searchResEntry':
                continue
            entries.setdefault(item['dn'], item)
            if max_entries and len(entries) >= max_entries:
                break

    import ldap3
    try:
        for chunk in tqdm([logins[i:i + 50] for i in range(0, len(logins), 50)], desc='Logins', unit='batch'):
            collect(login_filter(chunk), settings.search_base, ldap3.SUBTREE, 'Searching')
        found = {str(e['attributes'].get('sAMAccountName', '')).lower() for e in entries.values()}
        for missing in sorted({login.lower() for login in logins} - found):
            click.echo(f"not found: {missing}", err=True)
        if ldap_filter:
            collect(f"(&(objectclass=person){ldap_filter})", settings.search_base, ldap3.SUBTREE,
                    'Filter', limit)

        if with_managers:
            pending = set(entries)
            for _ in range(MAX_MANAGER_LEVELS):
                managers = {str(_first(entries[dn]['attributes'].get('manager')))
                            for dn in pending} - {''} - set(entries)
                if not managers:
                    break
                before = set(entries)
                for dn in tqdm(sorted(managers), desc='Managers', unit='entry'):
                    collect('(objectclass=person)', dn, ldap3.BASE, 'Manager')
                pending = set(entries) - before
        ldif = connection.response_to_ldif(search_result=list(entries.values()))
    finally:
        directory.close()

    header = f"# Copied from the production directory by export_ldap_to_mokapi.py: personal data, do not commit.\n" \
             f"dn:\nnamingContexts: {settings.search_base}\n\n"
    output.write_text(header + ldif, encoding='utf-8', newline='\n')
    click.echo(f"Wrote {len(entries)} entries to {output}")


def _first(value) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ''
    return str(value or '').strip()


if __name__ == '__main__':
    main()
