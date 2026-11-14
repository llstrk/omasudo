#!/bin/bash
# Installs the polkit rule that notes which process asked for each action, so
# the dialog can show the exact requesting command (also for D-Bus callers such
# as systemctl, not just pkexec). Normally run by `bin/omasudo setup`.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo $0" >&2; exit 1; }
src=$(cd "$(dirname "$0")" && pwd)

install -Dm644 "$src/00-subject-note.rules" /etc/polkit-1/rules.d/00-subject-note.rules
install -Dm755 "$src/polkit-subject-note"   /usr/local/lib/polkit-subject-note
install -Dm644 "$src/subject-note.conf"     /etc/systemd/system/polkit.service.d/subject-note.conf
# A root-owned copy, so the rule can be removed after the plugin folder is gone.
install -Dm755 "$src/uninstall.sh"          /usr/local/lib/omasudo/uninstall.sh
# rules.d is not readable by users; this lets `omasudo status` check the rule.
sha256sum < "$src/00-subject-note.rules" | cut -d" " -f1 > /usr/local/lib/omasudo/rule.sha256
chmod 644 /usr/local/lib/omasudo/rule.sha256

# Before the rename to omasudo this lived in /usr/local/lib/polkit-review.
rm -rf /usr/local/lib/polkit-review

systemctl daemon-reload
# polkitd's sandbox only gains the /run/polkit-subject directory on restart.
# The Omasudo dialog registers again within a few seconds.
systemctl restart polkit.service
[[ -d /run/polkit-subject ]] || { echo "error: /run/polkit-subject was not created" >&2; exit 1; }
echo "Installed the polkit rule."
