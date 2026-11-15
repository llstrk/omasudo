#!/usr/bin/env python3
"""Which agents review requests: discovery, the picker, and the config file.

Usage:
  agents.py list [--json]   agents found on this machine
  agents.py get             the chosen reviewers, one per line
  agents.py configured      exit 0 when a choice has been made (even "none")
  agents.py set [name...]   choose reviewers in order; no names = no AI review
  agents.py pick            choose in the terminal with gum

The choice lives in ~/.config/omasudo/config.json:
  {"reviewers": ["pi", "claude"], "agents": {"claude": {"model": "opus", "effort": "low"}}}
The first reviewer is asked first; the next ones only when it can't answer.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reviewers  # noqa: E402

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "omasudo" / "config.json"
OMARCHY_DEFAULT = Path.home() / ".config/omarchy/defaults/agent"
# Omarchy's list (omarchy-default-agent's usage line) when it can't be read.
KNOWN = ["pi", "omp", "opencode", "ori", "claude", "codex", "grok", "openclaw", "agy", "hermes", "copilot",
         "crush", "cursor-agent", "muse", "kimi", "qwen", "dsh", "mcode", "kiro-cli", "freebuff", "kilo",
         "devin", "amp", "commandcode"]


def known_agents():
    src = shutil.which("omarchy-default-agent")
    try:
        m = re.search(r"Usage: omarchy-default-agent <([\w|-]+)>", Path(src).read_text()) if src else None
    except OSError:
        m = None
    names = m.group(1).split("|") if m else KNOWN
    return list(dict.fromkeys(reviewers.SUPPORTED + names))


def omarchy_default():
    try:
        return OMARCHY_DEFAULT.read_text().strip()
    except OSError:
        return ""


def signed_in():
    """provider -> whether its active Omarchy account is signed in."""
    if not shutil.which("omarchy-agent-account-list"):
        return {}
    try:
        out = subprocess.run(["omarchy-agent-account-list", "--json"], capture_output=True, text=True, timeout=30).stdout
        out = json.loads(out)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    result = {}
    for p in out if isinstance(out, list) else []:
        accts = [a for a in p.get("accounts", []) if a.get("id") == p.get("active")] or p.get("accounts", [])
        if accts:
            result[p.get("provider")] = bool(accts[0].get("signedIn"))
    return result


def installed(name):
    """On PATH and really installed: mise shims and command wrappers exist
    for tools that are only declared, and running one would install it."""
    path = shutil.which(name)
    if not path:
        return False
    if "/mise/" in path or os.path.basename(os.path.realpath(path)) == "mise":
        try:
            return subprocess.run(["mise", "which", name], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    return True


def discover():
    default, accounts = omarchy_default(), signed_in()
    found = []
    for name in known_agents():
        if not installed(name):
            continue
        found.append({
            "name": name,
            "supported": name in reviewers.SUPPORTED,
            "default": name == default,
            "signedIn": accounts.get(name),  # None: Omarchy doesn't track this agent's sign-in
        })
    # Omarchy's default first, then signed in, then the rest in Omarchy's order.
    found.sort(key=lambda a: (not a["default"], a["signedIn"] is False))
    return found


def describe(a):
    bits = []
    if a["default"]:
        bits.append("Omarchy default")
    bits.append({True: "signed in", False: "not signed in", None: "installed"}[a["signedIn"]])
    if not a["supported"]:
        bits.append("not supported yet")
    return ", ".join(bits)


def load():
    try:
        data = json.loads(CONFIG.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(names):
    data = load()
    data["reviewers"] = names
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_name(CONFIG.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, CONFIG)


# Colours by terminal palette number, so they follow the Omarchy theme.
ACCENT, GOOD, WARN, MUTED = 4, 2, 3, 7  # 8 (bright black) is unreadable in some themes
DELIM = "\x1f"  # between a gum option's label and the value it prints


def paint(text, colour=None, bold=False):
    codes = (["1"] if bold else []) + ([str(30 + colour if colour < 8 else 82 + colour)] if colour is not None else [])
    return f"\033[{';'.join(codes)}m{text}\033[0m" if codes else text


BADGE = "\033[1;30;44m omasudo \033[0m"  # black on the theme's blue


def screen(*lines):
    """Starts a fresh screen: omasudo's title, then lines, indented."""
    if sys.stdout.isatty():
        sys.stdout.write("\033[H\033[2J")
    print()
    print("  " + BADGE + "  who reviews root requests from agents")
    print()
    for line in lines:
        print("  " + line if line else "")
    sys.stdout.flush()


def gum_choose(header, options, selected=None):
    """options: [(label, value)]; returns the chosen value, None on Esc."""
    # Omarchy's GUM_CHOOSE_* variables theme the rest.
    args = ["gum", "choose", "--header", "  " + header, "--label-delimiter", DELIM, "--cursor", "  › "]
    if selected:
        args += ["--selected", selected]
    p = subprocess.run(args + [f"{label}{DELIM}{value}" for label, value in options], stdout=subprocess.PIPE, text=True)
    if p.returncode != 0:
        erase_gum_line()
        return None
    return p.stdout.strip()


def erase_gum_line():
    """On Esc gum leaves "nothing selected" under the screen (on stderr, where
    it also draws, so it can't be silenced); our own message replaces it."""
    if sys.stderr.isatty():
        sys.stderr.write("\033[1A\033[2K")
        sys.stderr.flush()


def option(a, width):
    """An agent as a picker row: name, then a dot and what Omarchy knows."""
    ready = a["signedIn"] is not False
    status = paint("●", GOOD) + " " + ("signed in" if a["signedIn"] else "installed") if ready \
        else paint("○ not signed in", WARN)
    extra = paint("  Omarchy default", ACCENT) if a["default"] else ""
    return f"{paint(a['name'].ljust(width), bold=ready)}  {status}{extra}"


def pick():
    found = discover()
    usable = [a for a in found if a["supported"]]
    unsupported = [a["name"] for a in found if not a["supported"]]
    width = max([len(a["name"]) for a in usable] + [6])
    default = next((a for a in found if a["default"]), None)

    intro = [
        "Before you type your password for an agent, a second agent reads the",
        "command and tells you what it will really do. It never sees your home folder.",
        "",
    ]
    notes = []
    # The polkit rule step's outcome (bin/omasudo), cleared off screen by now.
    kind, _, text = os.environ.get("OMASUDO_NOTE", "").partition(":")
    if text:
        intro = [paint("✓ " + text, GOOD) if kind == "ok" else paint(text, MUTED), ""] + intro
    if default and not default["supported"]:
        notes.append(paint(f"Your default agent, {default['name']}, can't review yet.", WARN))
    if unsupported:
        notes.append(paint("Also installed, not supported yet: " + ", ".join(unsupported), MUTED))
    if not usable:
        notes.append(paint("No supported agent found: install one of " + ", ".join(reviewers.SUPPORTED), WARN))
    screen(*intro, *notes, *([""] if notes else []))

    rows = [(option(a, width), a["name"]) for a in usable]
    rows.append((f"{paint('No AI review', bold=True)}  {paint('just show the command', MUTED)}", "none"))
    # The current choice when there is one, else Omarchy's default agent.
    current = load().get("reviewers")
    configured = isinstance(current, list)
    first = (current[0] if current else "none") if configured else (default["name"] if default else None)
    start = next((l for l, n in rows if n == first), None) \
        or next((option(a, width) for a in usable if a["signedIn"] is not False), None)
    choice = gum_choose("Review with", rows, start)
    if choice is None:
        print("  Nothing changed." if configured else "  Nothing changed; asking again next time the shell starts.")
        return 0  # not an error: Omarchy's terminal would show "failed"
    change = paint(f"Change it any time: run {pretty_path()}", MUTED)
    if choice == "none":
        save([])
        screen(paint("✓", GOOD) + " No AI review: the dialog shows the command only.", "", change)
        return 0

    chosen = [choice]
    while True:
        rest = [(l, n) for l, n in rows[:-1] if n not in chosen]
        if not rest:
            break
        screen("Reviews  " + order(chosen) + paint("  → …", MUTED), "",
               f"A fallback is asked when {chosen[-1]} can't answer: offline, out of quota or too slow.", "")
        # The first stop is "no fallback at all"; after that the list is done.
        stop = "No fallback" if len(chosen) == 1 else "Done"
        nxt = gum_choose(f"If {chosen[-1]} can't answer, fall back to", [(paint(stop, bold=True), "none")] + rest)
        if nxt is None or nxt == "none":
            break
        chosen.append(nxt)
    save(chosen)
    screen(paint("✓ Saved", GOOD, bold=True), "", "Reviews  " + order(chosen), "", change)
    print()
    return 0


def order(names):
    return paint(" → ", MUTED).join(paint(n, bold=True) for n in names)


def pretty_path():
    """How to run omasudo: bin/omasudo passes `omasudo` when that command runs
    this checkout."""
    if os.environ.get("OMASUDO_ME"):
        return os.environ["OMASUDO_ME"]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "omasudo")
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        found = discover()
        if "--json" in sys.argv:
            print(json.dumps(found))
        else:
            for a in found:
                print(f"{a['name']:<14} {describe(a)}")
    elif cmd == "get":
        for n in load().get("reviewers", []):
            print(n)
    elif cmd == "configured":
        return 0 if isinstance(load().get("reviewers"), list) else 1
    elif cmd == "set":
        names = sys.argv[2:]
        bad = [n for n in names if n not in reviewers.SUPPORTED]
        if bad:
            sys.exit(f"Not supported as reviewers: {', '.join(bad)} (supported: {', '.join(reviewers.SUPPORTED)})")
        save(list(dict.fromkeys(names)))
    elif cmd == "pick":
        return pick()
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
