#!/usr/bin/env sh
# Installs the systemd template units for the bot and the web UI/API.
# Usage (from the repository root): sudo deploy/install_services.sh [user]
# Then:  sudo systemctl enable --now gyrobot@<env-name> gyrobot-web@<env-name>
set -eu

user="${1:-${SUDO_USER:-$(id -un)}}"
dir="$(realpath .)"
uv="$(sudo -u "$user" sh -lc 'command -v uv')"

for unit in deploy/systemd/*.service; do
    sed -e "s|@USER@|$user|g" -e "s|@DIR@|$dir|g" -e "s|@UV@|$uv|g" "$unit" \
        > "/etc/systemd/system/$(basename "$unit")"
done
systemctl daemon-reload
echo "Installed for user $user, directory $dir, uv $uv"
