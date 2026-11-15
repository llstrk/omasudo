# Changelog

## 0.5.0
- Choose the reviewer: Claude Code, Codex, pi, omp, opencode or Grok, with fallbacks in order, or no AI review. Setup lists the agents it finds, marks the Omarchy default and which are signed in, and starts on the default. Running `omasudo` opens setup again, starting on the current reviewer; `omasudo agents` lists the agents. Existing installs are asked once.
- An `omasudo` command: the dialog adds `~/.local/bin/omasudo`, which runs the plugin, so `omasudo reviewer` works from any terminal. It is also in the Omarchy menu (Super+Space search, Apps) and the app launcher, through `~/.local/share/applications/omasudo.desktop`. Files there it didn't write are left alone; removing the plugin removes both.
- Evidence first: man-page entries for the given subcommands and flags, packages and unit files go into the prompt, so reviewers seldom need tools and answer faster.
- pi, omp, opencode and Grok can read, search and list files to look further, inside a bubblewrap sandbox that shows only system locations and the agent's own settings; never the rest of your home folder. Without bubblewrap they run with their tools off. Codex stays without tools.
- A clearer first-run screen: the picker and the polkit rule step are short, in the theme's colours, one question at a time.
- Claude Code, Codex and Grok use the account Omarchy's agents panel marks active.
- Executable specs in Gherkin (`features/`, run by `tests/gherkin.py`), as in omaprofile.
- The dialog names the agent that answered. `OMASUDO_MODEL`/`OMASUDO_EFFORT` are replaced by `agents` in `~/.config/omasudo/config.json`.

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
