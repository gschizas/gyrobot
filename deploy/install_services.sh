#!/usr/bin/env sh
# Installs the systemd template units for the bot and the web UI/API.
# Usage (from the repository root): sudo deploy/install_services.sh [--company <name>] [user]
# Then:  sudo systemctl enable --now gyrobot@<env-name> gyrobot-web@<env-name>
# The company (for /opt/<company>/) is detected by deploy/company.sh unless --company is given.
set -eu

explicit=""
if [ "${1:-}" = "--company" ]; then
    explicit="${2:?--company needs a value}"
    shift 2
fi

. "$(dirname "$0")/company.sh"
company="$(resolve_company "$explicit")"

user="${1:-${SUDO_USER:-$(id -un)}}"
dir="$(realpath .)"
uv="$(sudo -u "$user" sh -lc 'command -v uv')"

if [ "$dir" != "/opt/$company/gyrobot" ]; then
    echo "Warning: installing from $dir, not /opt/$company/gyrobot" >&2
fi

for unit in deploy/systemd/*.service; do
    sed -e "s|@USER@|$user|g" -e "s|@DIR@|$dir|g" -e "s|@UV@|$uv|g" -e "s|@COMPANY@|$company|g" "$unit" \
        > "/etc/systemd/system/$(basename "$unit")"
done
systemctl daemon-reload
echo "Installed for user $user, company $company, directory $dir, uv $uv"
