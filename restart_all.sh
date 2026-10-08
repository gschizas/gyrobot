#!/bin/sh
# Restarts every enabled gyrobot instance (bot and web), e.g. gyrobot@eu and gyrobot-web@eu.
# Instances are enabled with: sudo systemctl enable --now gyrobot@<env-name>
set -eu

units=$(find /etc/systemd/system/multi-user.target.wants \( -name 'gyrobot@*.service' -o -name 'gyrobot-web@*.service' \) -printf '%f\n')
if [ -z "$units" ]; then
    echo "No enabled gyrobot instances found" >&2
    exit 1
fi
echo "$units" | xargs sudo systemctl restart
echo "$units" | sed 's/^/restarted /'
