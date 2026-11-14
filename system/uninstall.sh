#!/bin/bash
# Removes what install.sh added. Run: sudo ./system/uninstall.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo $0" >&2; exit 1; }

rm -f /etc/polkit-1/rules.d/00-subject-note.rules \
      /usr/local/lib/polkit-subject-note \
      /etc/systemd/system/polkit.service.d/subject-note.conf
rmdir --ignore-fail-on-non-empty /etc/systemd/system/polkit.service.d 2>/dev/null || true
systemctl daemon-reload
systemctl restart polkit.service
echo "Removed. Now run: omarchy restart shell"
