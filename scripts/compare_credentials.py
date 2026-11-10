#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["ruamel.yaml"]
# ///
"""Find out which credentials are repeated across config/*.credentials.yml, and whether the copies agree.

It never prints a secret, only a short fingerprint (the first 8 hex digits of its SHA-256), so two places with the
same fingerprint hold the same value.

1. Service principals (tenantId/servicePrincipalId/servicePrincipalKey, or tenant_id/client_id/client_secret) are
   grouped by tenant and application id; each group lists where it appears and flags differing secrets.
2. Any other string value (12+ characters) found in more than one place, such as a shared token.

Usage:
  uv run scripts/compare_credentials.py [--dir config] [--glob "*.credentials.yml"]
Exit status is 1 if a service principal has differing secrets.
"""
import argparse
import hashlib
import pathlib
import sys
from collections import defaultdict

from ruamel.yaml import YAML

SP_KEYS = (('tenantId', 'servicePrincipalId', 'servicePrincipalKey'), ('tenant_id', 'client_id', 'client_secret'))
MIN_LENGTH = 12


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:8]


def walk(node, path: str, sink_sp: list, sink_values: list) -> None:
    if isinstance(node, dict):
        skip: set = set()
        for tenant_key, id_key, secret_key in SP_KEYS:
            if {tenant_key, id_key, secret_key} <= node.keys():
                sink_sp.append((path, str(node[tenant_key]), str(node[id_key]), str(node[secret_key])))
                skip = {tenant_key, id_key, secret_key}
                break
        for key, child in node.items():
            if key not in skip:
                walk(child, f"{path}.{key}" if path else str(key), sink_sp, sink_values)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            walk(child, f"{path}[{index}]", sink_sp, sink_values)
    elif isinstance(node, str) and len(node.strip()) >= MIN_LENGTH:
        sink_values.append((path, node.strip()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dir', default='config')
    parser.add_argument('--glob', default='*.credentials.yml')
    args = parser.parse_args()

    files = sorted(pathlib.Path(args.dir).glob(args.glob))
    if not files:
        sys.exit(f"No {args.glob} files in {args.dir}")

    yaml = YAML(typ='safe')
    principals: list[tuple[str, str, str, str]] = []
    values: list[tuple[str, str]] = []
    for file in files:
        with file.open(encoding='utf-8') as f:
            walk(yaml.load(f), file.name, principals, values)
    print(f"Read {len(files)} file(s): {', '.join(f.name for f in files)}")

    groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for path, tenant, client_id, secret in principals:
        groups[(tenant, client_id)].append((path, fingerprint(secret)))

    differing = 0
    print(f"\n== Service principals: {len(groups)} distinct application(s) in {len(principals)} place(s)")
    for (tenant, client_id), places in sorted(groups.items()):
        fingerprints = {fp for _, fp in places}
        status = 'same secret everywhere' if len(fingerprints) == 1 else 'SECRETS DIFFER'
        if len(fingerprints) > 1:
            differing += 1
        print(f"\n  application {client_id} (tenant {tenant}): {len(places)} place(s), {status}")
        for path, fp in places:
            print(f"    {fp}  {path}")

    repeated: dict[str, list[str]] = defaultdict(list)
    for path, value in values:
        repeated[fingerprint(value)].append(path)
    repeated = {fp: paths for fp, paths in repeated.items() if len(paths) > 1}
    print(f"\n== Other values repeated in more than one place: {len(repeated)}")
    for fp, paths in sorted(repeated.items()):
        print(f"  {fp}")
        for path in paths:
            print(f"    {path}")

    return 1 if differing else 0


if __name__ == '__main__':
    sys.exit(main())
