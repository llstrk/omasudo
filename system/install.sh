#!/bin/bash
# Installs the polkit rule that records which process asked for each action,
# so the dialog can show the exact requesting command (also for D-Bus callers
# like systemctl, not just pkexec). Run once: sudo ./system/install.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo $0" >&2; exit 1; }
src=$(cd "$(dirname "$0")" && pwd)

install -Dm644 "$src/00-subject-note.rules" /etc/polkit-1/rules.d/00-subject-note.rules
install -Dm755 "$src/polkit-subject-note"   /usr/local/lib/polkit-subject-note
install -Dm644 "$src/subject-note.conf"     /etc/systemd/system/polkit.service.d/subject-note.conf
systemctl daemon-reload
systemctl restart polkit.service

[[ -d /run/polkit-subject ]] || { echo "warning: /run/polkit-subject was not created" >&2; exit 1; }
echo "Installed. Restarting polkit drops the desktop's polkit agent, so now run:"
echo "  omarchy restart shell"
