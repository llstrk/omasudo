#!/usr/bin/env python3
"""Describe the process behind a polkit request, for the auth dialog.

Usage: request-info.py <action-id>
Prints one JSON object on stdout. Nothing is written to disk or logged.

The requester PID comes from /run/polkit-subject/<action-id>, written by
/etc/polkit-1/rules.d/00-subject-note.rules. Without it, pkexec requests fall
back to the newest running pkexec; other requests are reported as unknown.
"""
import hashlib
import json
import os
import re
import shlex
import sys
import time
import unicodedata

NOTE_DIR = "/run/polkit-subject"
NOTE_MAX_AGE = 30.0  # seconds
AGENTS = {"claude", "pi", "omp", "codex", "opencode", "herdr", "aider", "gemini", "crush", "amp"}
# Walking up stops at these: everything above is the desktop, not the requester.
STOP = {"systemd", "omarchy-shell", "quickshell", "qs", "Hyprland", "uwsm", "sddm", "sddm-helper", "login", "sshd", "tmux: server"}
MAX_CMD = 4000
MAX_CHAIN = 12
MAX_FILES = 4  # files named in argv, passed on for the reviewer to read


def read(path, binary=False):
    try:
        with open(path, "rb" if binary else "r") as f:
            return f.read()
    except OSError:
        return None


def proc_info(pid):
    raw = read(f"/proc/{pid}/cmdline", binary=True)
    stat = read(f"/proc/{pid}/stat")
    if raw is None or stat is None:
        return None
    # surrogateescape keeps invalid UTF-8 bytes recoverable, so they are shown
    # as \xHH instead of being silently replaced.
    argv = [a.decode("utf-8", "surrogateescape") for a in raw.split(b"\0") if a]
    # comm is in parens and may contain spaces/parens; ppid follows the last ')'.
    rparen = stat.rfind(")")
    comm = stat[stat.find("(") + 1:rparen]
    rest = stat[rparen + 2:].split()
    ppid = int(rest[1]) if len(rest) > 1 else 0
    start = int(rest[19]) if len(rest) > 19 else 0
    exe = argv[0].rsplit("/", 1)[-1] if argv else comm
    return {"pid": pid, "ppid": ppid, "comm": comm, "exe": exe, "argv": argv, "start": start}


def hidden(ch):
    """Characters that render invisibly or reorder text: controls, format and
    bidi marks (U+202E etc.), undecodable bytes, and non-ASCII spaces."""
    if ch == " ":
        return False
    cat = unicodedata.category(ch)
    return cat[0] == "C" or cat[0] == "Z"


def esc(ch):
    o = ord(ch)
    if 0xDC80 <= o <= 0xDCFF:  # undecodable byte (surrogateescape)
        return f"\\x{o - 0xDC00:02x}"
    if ch == "\n":
        return "\\n"
    if ch == "\t":
        return "\\t"
    if o < 0x80:
        return f"\\x{o:02x}"
    return f"\\u{o:04x}" if o <= 0xFFFF else f"\\U{o:08x}"


def visible(s, keep=""):
    return "".join(c if c in keep or not hidden(c) else esc(c) for c in s)


def quote(arg):
    """shlex.quote, but an argument with hidden characters becomes bash $'...'
    with them escaped, so what is displayed is what will run."""
    if not any(hidden(c) for c in arg):
        return shlex.quote(arg)
    body = "".join(esc(c) if hidden(c) else "\\\\" if c == "\\" else "\\'" if c == "'" else c
                   for c in arg)
    return "$'" + body + "'"


def join(argv):
    s = " ".join(quote(a) for a in argv)
    return s if len(s) <= MAX_CMD else s[:MAX_CMD] + " …"


def named_files(subject):
    """(arg, path, stat) for each argv element that names an existing regular file."""
    cwd = None
    try:
        cwd = os.readlink(f"/proc/{subject['pid']}/cwd")
    except OSError:
        pass  # setuid pkexec: cwd not readable; relative paths fall back to ours
    out = []
    for arg in subject["argv"][1:]:
        if not arg or arg.startswith("-") or len(arg) > 4096:
            continue
        path = os.path.normpath(arg if os.path.isabs(arg) else os.path.join(cwd or os.getcwd(), arg))
        try:
            st = os.stat(path)
        except OSError:
            continue
        if os.path.isfile(path):
            out.append((arg, path, st))
    return out


def cache_key(action_id, subject, files):
    """Hash of action + exact argv + contents of any files named in argv.

    Lets the dialog reuse a recent verdict for an identical retry, but not when
    e.g. `pkexec bash /tmp/x.sh` runs again after x.sh was edited."""
    h = hashlib.sha256()
    h.update(action_id.encode() + b"\0")
    for arg in subject["argv"]:
        h.update(arg.encode("utf-8", "surrogateescape") + b"\0")
    for _arg, path, st in files:
        h.update(path.encode("utf-8", "surrogateescape") + b"\0")
        try:
            if st.st_size > 8 * 1024 * 1024:
                raise OSError
            with open(path, "rb") as f:
                h.update(b"F" + hashlib.sha256(f.read()).digest())
        except OSError:
            # Unreadable or huge: fall back to identity + mtime, so changes still miss.
            h.update(f"S{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()


def pid_from_note(action_id):
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", action_id):
        return None
    text = read(f"{NOTE_DIR}/{action_id}")
    if not text:
        return None
    try:
        ts, pid = text.split()
        if time.time() - float(ts) > NOTE_MAX_AGE:
            return None
        return int(pid)
    except ValueError:
        return None


def newest_pkexec():
    best = None
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        if (read(f"/proc/{d}/comm") or "").strip() != "pkexec":
            continue
        info = proc_info(int(d))
        if info and (best is None or info["start"] > best["start"]):
            best = info
    return best["pid"] if best else None


def main():
    action_id = sys.argv[1] if len(sys.argv) > 1 else ""
    out = {"found": False, "exact": False}
    pid = pid_from_note(action_id)
    if pid:
        out["exact"] = True
    elif action_id == "org.freedesktop.policykit.exec":
        pid = newest_pkexec()
    subject = proc_info(pid) if pid else None
    if not subject:
        print(json.dumps(out))
        return

    chain = []
    cur = subject
    while cur and len(chain) < MAX_CHAIN:
        chain.append(cur)
        if cur["ppid"] <= 1 or cur["comm"] in STOP or cur["exe"] in STOP:
            break
        cur = proc_info(cur["ppid"])

    # The nearest shell running a -c script above the subject: usually the
    # agent's full tool command, which gives the reviewer context.
    parent_cmd = ""
    for p in chain[1:]:
        a = p["argv"]
        if p["exe"] in ("bash", "sh", "zsh", "fish", "dash") and "-c" in a:
            i = a.index("-c")
            if i + 1 < len(a):
                parent_cmd = visible(a[i + 1][:MAX_CMD], keep="\n\t")
                break

    agent = next((p["exe"] if p["exe"] in AGENTS else p["comm"] for p in chain
                  if p["exe"] in AGENTS or p["comm"] in AGENTS), "")

    files = named_files(subject)
    out.update({
        "found": True,
        "pid": subject["pid"],
        "key": cache_key(action_id, subject, files),
        "command": join(subject["argv"]) or visible(subject["comm"]),
        "parentCommand": parent_cmd,
        "chain": [visible(p["exe"] or p["comm"]) for p in reversed(chain) if p["comm"] not in STOP],
        # Raw paths (not for display): review.py reads these and inlines them,
        # because the reviewer itself cannot read $HOME or /tmp.
        "files": [path for _a, path, _s in files[:MAX_FILES]],
        "agent": agent,
    })
    print(json.dumps(out))


if __name__ == "__main__":
    main()
