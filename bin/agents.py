#!/usr/bin/env python3
"""Which agents review requests: discovery, the picker, and the config file.

Usage:
  agents.py list [--json]   agents found on this machine
  agents.py get             the chosen reviewers, one per line
  agents.py configured      exit 0 when a choice has been made (even "none")
  agents.py set [name...]   choose reviewers in order; no names = no AI review
  agents.py pick            choose in the terminal with gum: reviewers, each
                            one's model and reasoning level, then offers a test

The choice lives in ~/.config/omasudo/config.json:
  {"reviewers": ["pi", "claude"], "agents": {"claude": {"model": "opus", "effort": "low"}}}
The first reviewer is asked first; the next ones only when it can't answer.
A model or level left out is the agent's own default (for Claude, omasudo's:
reviewers.DEFAULTS).
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto  # noqa: E402
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


def write(data):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_name(CONFIG.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, CONFIG)


def save(names):
    data = load()
    data["reviewers"] = names
    write(data)


def settings(name):
    """An agent's model and reasoning level from the config ({} = defaults)."""
    confs = load().get("agents")
    conf = confs.get(name) if isinstance(confs, dict) else None
    return conf if isinstance(conf, dict) else {}


def save_jobs(name, jobs):
    """How many requests omasudo test sends this agent at once, when its
    model isn't clearly a cloud one (bin/bench.py asks)."""
    data = load()
    confs = data.get("agents") if isinstance(data.get("agents"), dict) else {}
    conf = dict(confs.get(name)) if isinstance(confs.get(name), dict) else {}
    conf["jobs"] = jobs
    confs[name] = conf
    data["agents"] = confs
    write(data)


def save_setting(name, model, effort):
    """Sets an agent's model and level; "" removes it (the default). Other
    keys the user put there are kept."""
    data = load()
    confs = data.get("agents") if isinstance(data.get("agents"), dict) else {}
    conf = dict(confs.get(name)) if isinstance(confs.get(name), dict) else {}
    for k, v in (("model", model), ("effort", effort)):
        if v:
            conf[k] = v
        else:
            conf.pop(k, None)
    if conf:
        confs[name] = conf
    else:
        confs.pop(name, None)
    if confs:
        data["agents"] = confs
    else:
        data.pop("agents", None)
    write(data)


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
    """options: [(label, value)]; returns the chosen value, None on Esc.
    selected must have no comma: gum splits --selected at commas."""
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
    """An agent as a picker row: name, then a dot and what Omarchy knows, and
    how its current model and level did in omasudo test."""
    import bench
    ready = a["signedIn"] is not False
    status = paint("●", GOOD) + " " + ("signed in" if a["signedIn"] else "installed") if ready \
        else paint("○ not signed in", WARN)
    extra = paint("  Omarchy default", ACCENT) if a["default"] else ""
    return f"{paint(a['name'].ljust(width), bold=ready)}  {status}{extra}" \
        + tested(bench.result(a["name"], *bench.setting(a["name"], settings(a["name"]))))


def tested(result, level=None):
    """'  tested 13/16 good' for a picker row; nothing when never tested. An
    auto result names the level it found."""
    import bench
    if not result:
        return ""
    level = level or result.get("level")
    text = bench.summary(result) + (f" at {level}" if level else "")
    return "  " + paint(text, WARN if result.get("fail") or result.get("none") else MUTED)


DEFAULT = "(default)"  # the value of a "Default" row: no setting


def choose_setting(name, chosen):
    """The Model screen, then the Reasoning screen when the model has levels.
    Saves the choice; Esc keeps what was set."""
    import bench
    import models
    conf = settings(name)
    own = reviewers.DEFAULTS.get(name, {})
    progress = ["Reviews  " + order(chosen) + paint("  → …", MUTED), ""]
    screen(*progress, paint(f"Asking {name} which models it has…", MUTED))
    offer = models.offer(name)
    if not offer["models"]:
        return  # it lists none: nothing to choose
    current = conf.get("model", "")

    def model_row(label, model_key):
        r, level = bench.latest_for_model(name, model_key)
        return label + tested(r, level)

    rows = [(model_row(paint("Default", bold=True) + "  " + paint(own.get("model") or f"{name}'s own default", MUTED),
                       own.get("model", "")), DEFAULT)]
    rows += [(model_row(m["label"] + (paint(f"  {m['id']}", MUTED) if m["label"] != m["id"] else ""), m["id"]), m["id"])
             for m in offer["models"]]
    if current and current not in [m["id"] for m in offer["models"]]:
        rows.append((model_row(current + paint("  current", MUTED), current), current))
    screen(*progress, f"Which {name} model reviews. Bigger models judge better but answer slower.", "")
    start = next((l for l, v in rows if v == (current or DEFAULT)), None)
    picked = gum_choose(f"Model for {name}", rows, start)
    if picked is None:
        return
    model = "" if picked == DEFAULT else picked
    found = next((m for m in offer["models"] if m["id"] == model), None)
    efforts = found["efforts"] if found else offer["efforts"] if not model else []
    effort = conf.get("effort", "") if model == current else ""
    if efforts:
        model_key = model or own.get("model", "")
        # omasudo's own level applies to any model (bench.setting does the same).
        own_level = own.get("effort") or (found and found["default_effort"])
        rows = [(paint("Default", bold=True) + "  " + paint(own_level or f"{name}'s own default", MUTED)
                 + tested(bench.result(name, model_key, own.get("effort", ""))), DEFAULT)]
        rows += [(level + tested(bench.result(name, model_key, level)), level) for level in efforts]
        ladder = auto.ladder(efforts)
        if ladder:
            # Auto finds its level when tested; until then reviews use the top one.
            rows.append((paint("Auto", bold=True) + "  " + paint(f"the lowest of {' · '.join(ladder)} that passes the test", MUTED)
                         + (tested(bench.result(name, model_key, auto.AUTO)) or paint(f"  not tested: {ladder[-1]} until then", MUTED)),
                         auto.AUTO))
        screen(*progress, f"How long {name} thinks before answering. More is slower, and usually",
               "more careful; omasudo test shows how a level does.", "")
        start = next((l for l, v in rows if v == (effort if effort in efforts or effort == auto.AUTO else DEFAULT)), None)
        level = gum_choose(f"Reasoning for {name} · {model or 'default model'}", rows, start)
        if level is not None:
            effort = "" if level == DEFAULT else level
    else:
        effort = ""
    save_setting(name, model, effort)


def setting_line(name, width):
    """'pi        tensorfold/qwen, high  tested 13/16 good' for the Saved screen."""
    import bench
    model, effort = bench.setting(name, settings(name))
    text = ", ".join([model or "its default model", effort or "its default level"])
    return paint(name.ljust(width), bold=True) + "  " + text + tested(bench.result(name, model, effort))


def offer_test(chosen):
    """After the choice: test the first reviewer, or all, against requests
    with known answers (bin/bench.py)."""
    import bench
    finds = " · finds the level (auto)" if settings(chosen[0]).get("effort") == auto.AUTO else ""
    rows = [(f"Test {chosen[0]}" + paint(f"  {len(bench.CASES)} requests · a few minutes (longer on a local model){finds}", MUTED),
             "first")]
    if len(chosen) > 1:
        rows.append((f"Test all  " + order(chosen), "all"))
    rows.append(("Later" + paint(f"  run {pretty_path()} test", MUTED), "later"))
    print(paint(f"  omasudo knows the right answer to {len(bench.CASES)} root requests. A test shows how", MUTED))
    print(paint("  this choice judges them; nothing is run.", MUTED))
    print()
    picked = gum_choose("Test it now?", rows)
    if picked not in ("first", "all"):
        return
    for name in chosen[:1] if picked == "first" else chosen:
        bench.test(name, settings(name))
    print()


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
    choose_setting(choice, chosen)
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
        choose_setting(nxt, chosen)
    save(chosen)
    named = max(len(n) for n in chosen)
    screen(paint("✓ Saved", GOOD, bold=True), "", "Reviews  " + order(chosen), "",
           *[setting_line(n, named) for n in chosen], "", change, "")
    offer_test(chosen)
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
