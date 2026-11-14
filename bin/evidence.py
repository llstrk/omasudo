"""Collect what a reviewer needs to judge a command, so it needs no tools.

gather(command, scripts) returns a dict for the review prompt: for every
program in the command (and in scripts it runs) its package, the man-page
entries for the subcommands and flags it was given, and the unit files of any
systemd units it names. Only read-only commands run here (man, pacman -Qo,
systemctl cat/is-enabled/is-active), each with a short timeout.
"""
import os
import re
import shlex
import shutil
import subprocess

MAX_EXCERPT = 2500     # chars per man-page entry
MAX_MAN = 9000         # chars of man excerpts per program
MAX_UNIT = 3000        # chars per unit file
MAX_PROGRAMS = 6
MAX_UNITS = 4
# Wrappers whose arguments are another command.
WRAPPERS = {"sudo", "pkexec", "doas", "env", "nice", "ionice", "nohup", "time", "timeout", "stdbuf", "setsid", "chrt", "taskset", "flock"}
SHELLS = {"sh", "bash", "zsh", "dash", "fish"}
UNIT_RE = re.compile(r"^[\w@:.\\-]+\.(service|socket|timer|target|mount|automount|path|slice|scope|swap|device)$")
UNIT_VERBS = {"start", "stop", "restart", "reload", "try-restart", "reload-or-restart", "enable", "disable",
              "reenable", "mask", "unmask", "preset", "kill", "edit", "revert", "link", "isolate", "freeze", "thaw", "clean"}


def run(args, timeout=5, env=None):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, errors="replace",
                           env={**os.environ, **(env or {})}, stdin=subprocess.DEVNULL)
        return p.stdout if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def split(cmd):
    try:
        return shlex.split(cmd, comments=True)
    except ValueError:
        return cmd.split()


def commands_in(words):
    """Yield the argv of each simple command in a word list, looking through
    wrappers, `sh -c '...'`, and ; && || | separators."""
    cur = []
    for w in words + [";"]:
        if w in (";", "&&", "||", "|", "&"):
            yield from unwrap(cur)
            cur = []
        else:
            cur.append(w)


def unwrap(argv):
    while argv:
        name = os.path.basename(argv[0])
        if "=" in argv[0] and not argv[0].startswith("-"):  # FOO=bar cmd
            argv = argv[1:]
        elif name in WRAPPERS:
            argv = argv[1:]
            while argv and (argv[0].startswith("-") or "=" in argv[0] or argv[0].isdigit()):
                argv = argv[1:]
        elif name in SHELLS and "-c" in argv[1:]:
            i = argv.index("-c")
            if i + 1 < len(argv):
                yield from commands_in(split(argv[i + 1]))
            return
        else:
            yield argv
            return


def script_commands(text):
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            yield from commands_in(split(line))


def man_page(prog):
    return run(["man", prog], timeout=8, env={"MANWIDTH": "100", "MAN_KEEP_FORMATTING": "", "MANPAGER": "cat", "PAGER": "cat"})


def entries(page, token):
    """Man-page paragraphs that start with token: its line plus the lines
    indented deeper below it."""
    lines = page.splitlines()
    out = []
    pat = re.compile(r"^\s+" + re.escape(token) + r"(?=$|[\s,=\[<])")
    i = 0
    while i < len(lines):
        if pat.match(lines[i]):
            indent = len(lines[i]) - len(lines[i].lstrip())
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
                j += 1
            out.append("\n".join(l.rstrip() for l in lines[i:j]).strip()[:MAX_EXCERPT])
            i = j
        else:
            i += 1
    return out


def program_evidence(argv):
    prog = os.path.basename(argv[0])
    path = shutil.which(argv[0]) if "/" not in argv[0] else argv[0]
    info = {"program": prog}
    if path:
        owner = run(["pacman", "-Qo", "-q", path]).strip()
        info["package"] = owner or "not from a package"
    else:
        info["package"] = "not found on PATH"
    page = man_page(prog)
    if not page:
        info["man"] = "no man page"
        return info
    tokens = []
    for a in argv[1:]:
        if a.startswith("--"):
            tokens.append(a.split("=", 1)[0])
        elif re.fullmatch(r"-[A-Za-z0-9]+", a):
            tokens += ["-" + c for c in a[1:]]
        elif re.fullmatch(r"[a-z][\w-]*", a):
            tokens.append(a)
    excerpts, used = {}, 0
    for t in dict.fromkeys(tokens):
        found = entries(page, t)
        if found and used < MAX_MAN:
            text = "\n...\n".join(found)[:MAX_MAN - used]
            excerpts[t] = text
            used += len(text)
    missing = [t for t in dict.fromkeys(tokens) if t.startswith("-") and t not in excerpts]
    info["man_entries"] = excerpts
    if missing:
        info["flags_not_in_man_page"] = missing
    return info


def units_in(argv):
    if os.path.basename(argv[0]) != "systemctl":
        return []
    args = [a for a in argv[1:] if not a.startswith("-")]
    if not args or args[0] not in UNIT_VERBS:
        return []
    return [u if "." in u else u + ".service" for u in args[1:]]


def unit_evidence(unit):
    return {
        "unit": unit,
        "enabled": run(["systemctl", "is-enabled", unit]).strip() or "unknown",
        "active": run(["systemctl", "is-active", unit]).strip() or "unknown",
        "unit_file": run(["systemctl", "cat", "--no-pager", unit])[:MAX_UNIT] or "not found",
    }


def gather(command, scripts=()):
    cmds = list(commands_in(split(command)))
    for text in scripts:
        cmds += list(script_commands(text))
    programs, seen, units = [], {}, []
    for argv in cmds:
        if not argv or len(programs) >= MAX_PROGRAMS:
            continue
        key = os.path.basename(argv[0])
        if key in SHELLS and len(argv) > 1:
            continue  # a script; its contents are inlined as a named file
        ev = program_evidence(argv)
        if key in seen:  # same program again: merge new man entries
            seen[key]["man_entries"].update(ev.get("man_entries", {}))
        else:
            seen[key] = ev
            programs.append(ev)
        for u in units_in(argv):
            if u not in units and len(units) < MAX_UNITS:
                units.append(u)
    out = {"programs": programs}
    if units:
        out["units"] = [unit_evidence(u) for u in units]
    return out
