# Changelog

## 0.4.0
- Renamed from Polkit Review to Omasudo (plugin id `llstrk.omasudo`, command `bin/omasudo`). Reinstall: `omarchy plugin remove llstrk.polkit-review`, then add this repository.

## 0.3.0
- An update icon on the bar while a new version is out: click to update, right-click to hide it until the next one.
- Dragging the icon off the bar keeps the password dialog enabled (the plugin is also recorded in shell.json's plugins list).
- Without the icon on the bar, the notification is still sent, once per version.

## 0.2.2
- The update notice's Update button now stays in notification history and works after the toast is gone.

## 0.2.1
- Turning update checks off also silences a version an earlier check already found.
- A version bump alone no longer asks to restart the shell.

## 0.2.0
- First-run setup in a floating terminal: installs the polkit rule with one sudo prompt.
- The dialog reconnects by itself when polkitd restarts, so updates no longer break password prompts.
- Removing the plugin offers to remove its polkit rule too.
- Daily update check, with a notification and `omasudo update`.

## 0.1.0
- Polkit dialog that shows the requesting command and process chain, with a Claude verdict for coding-agent requests.
