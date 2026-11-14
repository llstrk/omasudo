#!/usr/bin/env python3
"""Update checks for Polkit Review, after omaprofile's.

  update.py              show what's new, ask, update through `omarchy plugin update`
  update.py --check      check now and print the result
  update.py --scheduled  the dialog's hourly call: at most one fetch a day, and a
                         notification with an Update button once per new version
  update.py --off/--on   stop or resume scheduled checks
  update.py --status     print the recorded state as JSON

A plugin added with `omarchy plugin add` is a git clone, so a check is a
`git fetch` of its origin and a look at the fetched manifest.json; nothing else
is contacted. State lives in ~/.local/state/polkit-review/update.json:

  checked    when the last check reached the repository (seconds)
  available  the newest version found, when newer than this one
  notified   the version a notification was shown for
  off        scheduled checks are off
"""
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "bin" / "polkit-review"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "polkit-review"
STATE = STATE_DIR / "update.json"
PLUGINS_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "omarchy" / "plugins"
CHECK_EVERY = 24 * 3600
FETCH_TIMEOUT = 30
FLOATING_TERMINAL = "omarchy-launch-floating-terminal-with-presentation"
# Changing these needs a shell restart: the running dialog keeps its compiled QML.
DIALOG_FILES = ["PolkitAgent.qml", "PolkitModel.js", "i18n", "manifest.json"]


class UpdateError(Exception):
    pass


def manifest(text=None):
    try:
        return json.loads(text if text is not None else (ROOT / "manifest.json").read_text())
    except (OSError, ValueError):
        return {}


PLUGIN_ID = str(manifest().get("id", "llstrk.polkit-review"))


def installed_version():
    return str(manifest().get("version", "0"))


def version_key(v):
    return tuple(int(n) if n.isdigit() else -1 for n in re.findall(r"\d+|[^\d.]+", v or "0"))


def newer(candidate, than):
    return bool(candidate) and version_key(candidate) > version_key(than)


def managed():
    """Installed by `omarchy plugin add`: this folder is the git clone in the plugins folder."""
    try:
        return ROOT.resolve() == (PLUGINS_DIR / PLUGIN_ID).resolve() and (ROOT / ".git").exists()
    except OSError:
        return False


def load_state():
    try:
        s = json.loads(STATE.read_text())
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, STATE)


def git(*args, timeout=FETCH_TIMEOUT):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0",
           "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")}
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          env=env, timeout=timeout)


def fetch():
    try:
        proc = git("fetch", "--quiet", "origin", "HEAD")
    except (OSError, subprocess.SubprocessError) as e:
        raise UpdateError(f"could not reach the repository: {e}") from e
    if proc.returncode != 0:
        lines = proc.stderr.strip().splitlines()
        raise UpdateError("could not reach the repository" + (f": {lines[-1]}" if lines else ""))


def fetched_file(name):
    proc = git("show", f"FETCH_HEAD:{name}", timeout=10)
    return proc.stdout if proc.returncode == 0 else ""


def fetched_version():
    version = manifest(fetched_file("manifest.json")).get("version")
    if not version:
        raise UpdateError("the repository has no readable manifest.json")
    return str(version)


def changes(changelog, after, upto):
    """CHANGELOG.md entries newer than `after`, up to `upto`, newest first."""
    out, current = [], None
    for line in changelog.splitlines():
        m = re.match(r"^##\s+\[?v?([0-9][^\]\s]*)", line)
        if m:
            v = m.group(1)
            current = (v, []) if newer(v, after) and not newer(v, upto) else None
            if current:
                out.append(current)
        elif current and line.strip().startswith(("- ", "* ")):
            current[1].append(line.strip()[2:].strip())
    return out


def check(scheduled=False):
    state = load_state()
    if scheduled:
        if not managed() or state.get("off"):
            return state
        if 0 <= time.time() - float(state.get("checked", 0) or 0) < CHECK_EVERY:
            return state
    fetch()
    latest = fetched_version()
    state["checked"] = int(time.time())
    state["available"] = latest if newer(latest, installed_version()) else None
    save_state(state)
    return state


def notify_with_buttons(summary, body, buttons):
    if not shutil.which("notify-send"):
        return ""
    argv = ["notify-send", "-a", "Polkit Review", "-i", "dialog-password"]
    for name, label in buttons:
        argv += ["-A", f"{name}={label}"]
    return subprocess.run([*argv, summary, body], capture_output=True, text=True).stdout.strip()


def open_updater():
    subprocess.Popen([FLOATING_TERMINAL, f"{shlex.quote(str(CLI))} update"],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def scheduled():
    """Quiet: offline or failing checks just wait for the next one."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE.with_suffix(".lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        try:
            state = check(scheduled=True)
        except Exception:  # noqa: BLE001
            return
        waiting = state.get("available")
        if not newer(waiting, installed_version()) or state.get("notified") == waiting:
            return
        state["notified"] = waiting
        save_state(state)
    news = changes(fetched_file("CHANGELOG.md"), installed_version(), waiting)
    body = " ".join(news[0][1][:2]) if news else ""
    choice = notify_with_buttons(f"Polkit Review {waiting} is available", body or "Update to see what's new.",
                                 [("update", "Update"), ("later", "Not now")])
    if choice == "update":
        open_updater()


def ask(question, default=True):
    print(f"{question} [{'Y/n' if default else 'y/N'}] ", end="", flush=True)
    answer = sys.stdin.readline().strip().lower()
    return default if not answer else answer in ("y", "yes")


def run():
    current = installed_version()
    if not managed():
        print(f"Polkit Review {current} runs from {ROOT}, not from a plugin Omarchy installed.\n"
              f"Update it with: cd {shlex.quote(str(ROOT))} && git pull")
        return 0
    try:
        latest = check().get("available")
    except UpdateError as e:
        print(f"polkit-review: {e}", file=sys.stderr)
        return 1
    if not newer(latest, current):
        print(f"Polkit Review {current} is up to date.")
        return 0

    print(f"Polkit Review {current} → {latest}\n")
    for version, lines in changes(fetched_file("CHANGELOG.md"), current, latest):
        print(version)
        for line in lines:
            print(f"  • {line}")
        print()
    if not ask("Update?"):
        print("Not updated.")
        return 0

    before = git("rev-parse", "HEAD", timeout=5).stdout.strip()
    proc = subprocess.run(["omarchy", "plugin", "update", PLUGIN_ID, "--yes"], capture_output=True, text=True)
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        print(f"Update failed: {lines[-1] if lines else f'exit {proc.returncode}'}\nStill on {current}.",
              file=sys.stderr)
        return 1
    print(f"Updated to {installed_version()}.")

    # bin/ changes apply at once; the dialog itself and the root rule need a step.
    changed = git("diff", "--name-only", before, "HEAD", "--", *DIALOG_FILES, "system", timeout=10).stdout.split()
    if any(not f.startswith("system/") for f in changed):
        print("\nThe password dialog changed; the running one keeps the old version until the shell restarts.")
        if ask("Restart the shell now?"):
            subprocess.run(["omarchy", "restart", "shell"], capture_output=True)
            print("Restarted.")
    status = subprocess.run([str(CLI), "status"], capture_output=True, text=True).stdout
    if "rule=outdated" in status:
        print("\nThe polkit rule changed too.")
        os.execv(str(CLI), [str(CLI), "setup"])
    return 0


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "":
        sys.exit(run())
    if arg == "--scheduled":
        scheduled()
    elif arg == "--check":
        try:
            latest = check().get("available")
        except UpdateError as e:
            sys.exit(f"polkit-review: {e}")
        print(f"{latest} available (installed {installed_version()})" if latest
              else f"{installed_version()} is up to date")
    elif arg in ("--off", "--on"):
        state = load_state()
        state["off"] = arg == "--off"
        save_state(state)
        print("Scheduled update checks are " + ("off." if state["off"] else "on."))
    elif arg == "--status":
        print(json.dumps({**load_state(), "installed": installed_version(), "managed": managed()}))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
