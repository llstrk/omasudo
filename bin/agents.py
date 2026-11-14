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
NONE = "No AI review (show the command only)"
NO_FALLBACK = "No fallback"


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


def gum_choose(header, options, selected=None):
    args = ["gum", "choose", "--header", header]
    if selected:
        args += ["--selected", selected]
    p = subprocess.run(args + options, stdout=subprocess.PIPE, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def pick():
    found = discover()
    usable = [a for a in found if a["supported"]]
    width = max([len(a["name"]) for a in found] + [6])
    lines = ["Choose who reviews agent requests", ""]
    if found:
        lines.append("Agents found on this machine:")
        lines += [f"  {a['name']:<{width}}  {describe(a)}" for a in found]
    else:
        lines.append("No coding agents found on this machine.")
    default = next((a for a in found if a["default"]), None)
    if default and not default["supported"]:
        lines += ["", f"Your default agent, {default['name']}, can't review yet; pick another."]
    lines += [
        "",
        "The reviewer gets the command, its process chain, and evidence omasudo",
        "gathers here (man-page entries, unit files, named scripts; secrets",
        "redacted). Codex and pi run with no tools; Claude has read-only tools",
        "that cannot read your home folder.",
    ]
    subprocess.run(["gum", "style", "--border", "rounded", "--padding", "1 2", "--width", "78", *lines])
    print()

    labels = {f"{a['name']} ({describe(a)})": a["name"] for a in usable}
    first_label = next((l for l, n in labels.items() if default and n == default["name"]), None)
    if not first_label:
        first_label = next((l for l, n in labels.items() if "not signed in" not in l), None)
    choice = gum_choose("Review agent requests with:", list(labels) + [NONE], first_label)
    if choice is None:
        print("Nothing changed; asking again next time the shell starts.")
        return 1
    if choice == NONE:
        save([])
        print("No AI review: the dialog shows the command only.")
        print(f"To choose a reviewer later: {os.path.dirname(os.path.abspath(__file__))}/omasudo reviewer")
        return 0

    chosen = [labels[choice]]
    while True:
        rest = [l for l, n in labels.items() if n not in chosen]
        if not rest:
            break
        nxt = gum_choose(f"If {chosen[-1]} can't answer, fall back to:", [NO_FALLBACK] + rest)
        if nxt is None or nxt == NO_FALLBACK:
            break
        chosen.append(labels[nxt])
    save(chosen)
    print("Reviews: " + " → ".join(chosen))
    print(f"Change with: {os.path.dirname(os.path.abspath(__file__))}/omasudo reviewer")
    return 0


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
