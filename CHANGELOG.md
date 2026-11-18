# Changelog

## 0.7.0
- `omasudo test` reviews several requests at a time; the rows still print in order. A model that clearly runs in the cloud gets 12 at a time; any other gets 2, since a server on this machine or the LAN answers a few at once and queues the rest, which then run out of time. Cloud is Claude, Grok and Codex unless they are pointed at a local server, and for pi, omp and opencode a provider at a public address or a built-in one that isn't a local server (ollama, LM Studio, ...). `--jobs N` sets how many. Ctrl+C stops the reviews running and skips the rest.
- Auto reasoning: pick "Auto" on the reasoning screen (or `omasudo test --effort auto`) and the test finds the lowest of low, medium and high that passes. It starts at low; a request that fails is asked again one level up, only that request, and the rest go on at the new level. A run that stepped up starts over at its last level, until a run passes at one level (kept, and reviews use it) or a request fails at high. Never xhigh or max. Until a level is found, reviews use high. A request with no answer is asked once more at the same level; it doesn't step up, and a run that still has one finds no level.

## 0.6.0
- Choose each reviewer's model and reasoning level: after an agent, setup lists the models and levels it offers (Claude Code, Codex, pi and omp; models only for opencode and Grok). Default leaves it to the agent.
- `omasudo test [agent]`, also offered at the end of setup: 24 root requests with known answers (15 of them dangerous) go through the same review as the dialog, and each verdict scores good (expected), okay (more cautious) or fail (less cautious). Nothing is run. The answers per expected verdict follow, with how many dangerous requests were called DANGEROUS. The counts are kept per agent, model and level, and the picker shows them.
- `omasudo test --blind`: a held-out set of 24 requests the prompt is never tuned on, to check that it generalizes. Printed, not kept.
- Sharper verdict definitions for reviewers: SAFE also covers routine changes undone by one obvious command that touch no files, packages or data; CAUTION is config edits, packages, deleted files and stopped services; DANGEROUS adds lasting root (sudoers, polkit rules, setuid) and code the reviewer can't see. Reviewers are told that long encoded blobs are redacted too.
- When Claude's safeguards decline to review a dangerous request, it is asked again on the model Claude Code itself switches to (Opus 4.8 for Opus, Sonnet 5 for Sonnet), and the dialog names that model. `claude -p` doesn't switch on its own, so `passwd -d root` used to get no verdict on Opus 5.5.
- Evidence shows where a path in the command really leads when it goes through a symlink, relative paths taken from the requester's folder: `rm -rf build-cache/` on a link to `/usr` is no longer a cache cleanup to a reviewer that can't look.

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
