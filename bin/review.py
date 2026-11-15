#!/usr/bin/env python3
"""Ask the chosen agent what a pending privileged request will actually do.

Usage: review.py '<json request>'
  request: {"actionId", "message", "command", "parentCommand", "chain", "files"}
Prints {"verdict", "summary", "details", "command", "reviewer"} as JSON on
stdout. verdict OFF means no reviewer was chosen (no AI review).

Reviewers come from ~/.config/omasudo/config.json (bin/agents.py), tried in
order until one answers. Evidence (man-page entries, unit files, files named
in the command) is gathered here first, so reviewers need no tools; see
bin/reviewers.py for how each one runs. Nothing is written to disk outside a
temporary directory, sessions are not saved, and obvious secrets are blanked
before anything leaves the machine.
"""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents  # noqa: E402
import evidence  # noqa: E402
import reviewers  # noqa: E402

BUDGET = 90  # seconds for all reviewers; keeps running after the dialog closes, result is cached
MAX_FILE = 32 * 1024  # bytes inlined per named file
MAX_FILES = 4

SECRET_PATTERNS = [
    # --password=x, --token x, -p x style flags
    (re.compile(r"(?i)(--?[\w-]*(?:pass(?:word|wd)?|token|secret|api[-_]?key|auth|credential)s?[\w-]*(?:=|\s+))(\"[^\"]*\"|'[^']*'|\S+)"), r"\1<redacted>"),
    # FOO_TOKEN=x env assignments
    (re.compile(r"\b([A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|CREDENTIAL)[A-Za-z0-9_]*=)(\"[^\"]*\"|'[^']*'|\S+)", re.I), r"\1<redacted>"),
    # HTTP auth headers
    (re.compile(r"(?i)((?:authorization|x-api-key|cookie)\s*:\s*)([^'\"\n]+)"), r"\1<redacted>"),
    # user:pass@ in URLs
    (re.compile(r"(://[^/\s:@]+:)([^@\s/]+)(@)"), r"\1<redacted>\3"),
    # well-known token shapes
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"), "<redacted>"),
    # long opaque hex/base64 blobs
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b|\b[A-Za-z0-9+/]{48,}={0,2}"), "<redacted>"),
]

def hidden(ch):
    return ch != " " and unicodedata.category(ch)[0] in "CZ"


def visible(s, keep=""):
    """Escape invisible/bidi/control characters so text shows as it is."""
    return "".join(c if c in keep or not hidden(c) else
                   f"\\u{ord(c):04x}" if ord(c) <= 0xFFFF else f"\\U{ord(c):08x}" for c in s)


def named_files(paths):
    out = []
    for path in paths[:MAX_FILES]:
        entry = {"path": path}
        try:
            with open(path, "rb") as f:
                data = f.read(MAX_FILE + 1)
                entry["size"] = os.fstat(f.fileno()).st_size
        except OSError as e:
            entry["error"] = e.strerror or "unreadable"
            out.append(entry)
            continue
        if b"\0" in data[:8192]:
            entry["content"] = None
            entry["note"] = "binary file, not shown"
        else:
            entry["content"] = redact(data[:MAX_FILE].decode("utf-8", "replace"))
            if len(data) > MAX_FILE:
                entry["note"] = f"truncated to the first {MAX_FILE} bytes"
        out.append(entry)
    return out


def die_with_parent():
    # Runs in the child before exec: if review.py dies, even by SIGKILL,
    # the kernel sends claude SIGTERM so it never outlives the dialog.
    import ctypes
    PR_SET_PDEATHSIG = 1
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def redact(s):
    for pat, rep in SECRET_PATTERNS:
        s = pat.sub(rep, s)
    return s


def emit(verdict, summary, details="", command="", reviewer=""):
    # command is the redacted form, safe for a notification.
    print(json.dumps({"verdict": verdict, "summary": summary, "details": details,
                      "command": command[:200], "reviewer": reviewer}))


current = {"proc": None}


def stop(*_):
    proc = current["proc"]
    if proc:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
    sys.exit(1)


def ask(name, prompt, conf, deadline):
    """One reviewer's answer, or raise with a short reason (no request text)."""
    if not agents.installed(name):
        raise RuntimeError("not installed")
    with tempfile.TemporaryDirectory(prefix="omasudo-", dir=os.environ.get("XDG_RUNTIME_DIR")) as cwd:
        argv, stdin, parse, env = reviewers.build(name, prompt, cwd, conf)
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env={**os.environ, **env},
                                    stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, start_new_session=True,
                                    preexec_fn=die_with_parent)
        except OSError:
            raise RuntimeError("could not start")
        current["proc"] = proc
        try:
            out, _ = proc.communicate(stdin, timeout=max(5, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
            proc.wait()
            raise RuntimeError("timed out")
        finally:
            current["proc"] = None
        if proc.returncode != 0:
            raise RuntimeError(f"exit {proc.returncode}")
        try:
            data = parse(out)
        except (OSError, ValueError, TypeError, AttributeError):
            raise RuntimeError("unreadable answer")
    if not isinstance(data, dict) or data.get("verdict") not in ("SAFE", "CAUTION", "DANGEROUS"):
        raise RuntimeError("no verdict")
    return data


def main():
    try:
        req = json.loads(sys.argv[1])
    except (IndexError, ValueError):
        emit("ERROR", "Bad review request.")
        return

    config = agents.load()
    names = config.get("reviewers")
    if not isinstance(names, list):
        emit("ERROR", "No reviewer chosen yet: run bin/omasudo reviewer.")
        return
    names = [n for n in names if n in reviewers.SUPPORTED]
    if not names:
        emit("OFF", "")
        return

    command = redact(req.get("command", ""))
    body = {
        "polkit_action": req.get("actionId", ""),
        "polkit_message": req.get("message", ""),
        "requesting_command": command,
        "process_chain": req.get("chain", []),
    }
    if req.get("parentCommand"):
        body["enclosing_shell_command"] = redact(req["parentCommand"])
    files = req.get("files")
    scripts = []
    if isinstance(files, list) and files:
        body["files_named_in_command"] = named_files([str(f) for f in files])
        scripts = [f["content"] for f in body["files_named_in_command"] if f.get("content")]
    try:
        body["evidence"] = evidence.gather(command, scripts)
    except Exception:  # evidence is a help, never a reason to give no verdict
        body["evidence"] = {"error": "could not gather evidence"}
    # json.dumps already escapes non-ASCII (so bidi tricks arrive as \uXXXX);
    # also escape "@" so nothing in the request can act as an @file mention.
    prompt = "<request>\n" + json.dumps(body, indent=2).replace("@", "\\u0040") + "\n</request>"

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    deadline = time.monotonic() + BUDGET
    failed = []
    for name in names:
        if time.monotonic() > deadline - 5:
            failed.append(f"{name}: out of time")
            continue
        try:
            data = ask(name, prompt, (config.get("agents") or {}).get(name, {}), deadline)
        except RuntimeError as e:
            failed.append(f"{name}: {e}")
            if os.environ.get("OMASUDO_DEBUG"):
                print(failed[-1], file=sys.stderr)
            continue
        emit(data["verdict"], visible(str(data.get("summary", ""))[:400]),
             visible(str(data.get("details", ""))[:1500], keep="\n"), command, name)
        return
    emit("ERROR", "No reviewer answered (" + "; ".join(failed) + "); judge the command yourself.")


if __name__ == "__main__":
    main()
