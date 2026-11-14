#!/bin/bash
# Removes what install.sh added. polkitd reloads rules by itself, so it is not
# restarted (which would also drop the desktop's polkit agent); the drop-in's
# tmpfs directory goes away at its next restart.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo $0" >&2; exit 1; }

rm -f /etc/polkit-1/rules.d/00-subject-note.rules \
      /usr/local/lib/polkit-subject-note \
      /etc/systemd/system/polkit.service.d/subject-note.conf \
      /usr/local/lib/omasudo/uninstall.sh \
      /usr/local/lib/omasudo/rule.sha256
rm -rf /usr/local/lib/polkit-review  # pre-rename location
rmdir /usr/local/lib/omasudo /etc/systemd/system/polkit.service.d 2>/dev/null || true
systemctl daemon-reload
echo "Removed Omasudo's polkit rule."
