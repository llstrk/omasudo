# Changelog

## 0.2.0
- First-run setup in a floating terminal: installs the polkit rule with one sudo prompt.
- The dialog reconnects by itself when polkitd restarts, so updates no longer break password prompts.
- Removing the plugin offers to remove its polkit rule too.
- Daily update check, with a notification and `polkit-review update`.

## 0.1.0
- Polkit dialog that shows the requesting command and process chain, with a Claude verdict for coding-agent requests.
