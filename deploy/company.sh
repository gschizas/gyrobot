#!/usr/bin/env sh
# Resolves the company name used in /opt/<company>/.
# The valid names are not stored in the repository: list them in the untracked deploy/site.env
# (see deploy/site.env.example). A candidate is accepted only if it is in that list.
# Source it and call:  company="$(resolve_company "$explicit")"
# Order: explicit value (--company / $COMPANY), an existing /opt/<company> directory, then the first
# label of the host's DNS suffix. Fails (non-zero, message on stderr) if nothing valid is found.

SITE_ENV="${SITE_ENV:-$(dirname "$0")/site.env}"
COMPANIES=""
if [ -f "$SITE_ENV" ]; then
    # shellcheck disable=SC1090
    . "$SITE_ENV"
fi

is_valid_company() {
    # lowercase letters only, so nothing odd can reach a path or a unit file
    case "$1" in ''|*[!a-z]*) return 1 ;; esac
    case " $COMPANIES " in *" $1 "*) return 0 ;; esac
    return 1
}

resolve_company() {
    if [ -z "$COMPANIES" ]; then
        echo "No valid companies configured: create $SITE_ENV (see deploy/site.env.example)." >&2
        return 1
    fi

    explicit="${1:-${COMPANY:-}}"
    if [ -n "$explicit" ]; then
        if is_valid_company "$explicit"; then echo "$explicit"; return 0; fi
        echo "Invalid company name." >&2
        return 1
    fi

    found=""
    count=0
    for dir in /opt/*/; do
        name="$(basename "$dir")"
        if is_valid_company "$name"; then found="$name"; count=$((count + 1)); fi
    done
    if [ "$count" -eq 1 ]; then echo "$found"; return 0; fi

    suffixes="$(dnsdomainname 2>/dev/null; sed -n 's/^\(search\|domain\)[[:space:]]\+//p' /etc/resolv.conf 2>/dev/null | tr ' ' '\n')"
    for suffix in $suffixes; do
        label="$(printf '%s' "$suffix" | cut -d. -f1 | tr 'A-Z' 'a-z')"
        if is_valid_company "$label"; then echo "$label"; return 0; fi
    done

    echo "Could not determine the company from /opt or the DNS suffix; pass --company <name>." >&2
    return 1
}
