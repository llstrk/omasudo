#!/usr/bin/python3
"""Stand-in for the coding agents, gum, mise and Omarchy's commands.

Linked under each tool's name in a scenario's bin folder, first on PATH. Every
call is appended to $FAKE_LOG as one JSON object; nothing reaches a real agent
or the desktop. What the scenario steers lives in $FAKE_DIR:

  accounts.json        what `omarchy-agent-account-list --json` prints
  mise-installed       tools `mise which` finds (one per line)
  gum-answers          labels `gum choose` picks, one per question; ESC or
                       running out is Esc
  <agent>.answer       what that agent replies (a JSON verdict or plain text)
  <agent>.fails        that agent exits 1
"""

import json
import os
import subprocess
import sys
from pathlib import Path

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
fake_dir = Path(os.environ["FAKE_DIR"])
AGENTS = {"claude", "codex", "pi", "omp", "opencode", "grok", "hermes", "kimi"}


def log(**entry):
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps({"tool": tool, "args": args, **entry}) + "\n")


def option(name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


if tool == "gum":
    if args[:1] == ["style"]:
        log()
        print("\n".join(a for a in args[1:] if not a.startswith("--") and a not in ("rounded", "1 2", "78")))
        sys.exit(0)
    if args[:1] == ["choose"]:
        header, selected = option("--header"), option("--selected")
        rest, skip = [], False
        for a in args[1:]:
            if skip:
                skip = False
            elif a in ("--header", "--selected"):
                skip = True
            else:
                rest.append(a)
        log(header=header, selected=selected, options=rest)
        queue = fake_dir / "gum-answers"
        lines = queue.read_text().splitlines() if queue.exists() else []
        if not lines or lines[0] == "ESC":
            print("nothing selected", file=sys.stderr)
            sys.exit(130)
        queue.write_text("".join(l + "\n" for l in lines[1:]))
        assert lines[0] in rest, f"gum: {lines[0]!r} is not offered: {rest}"
        print(lines[0])
        sys.exit(0)
    log()
    sys.exit(0)

if tool == "mise":
    log()
    found = (fake_dir / "mise-installed").read_text().split() if (fake_dir / "mise-installed").exists() else []
    sys.exit(0 if args[:1] == ["which"] and args[1:2] and args[1] in found else 1)

if tool == "omarchy-agent-account-list":
    log()
    print((fake_dir / "accounts.json").read_text() if (fake_dir / "accounts.json").exists() else "[]")
    sys.exit(0)

if tool == "omarchy-agent-account-exec":
    log()
    os.execvpe(args[0], args, {**os.environ, "FAKE_VIA_ACCOUNT": "1"})

if tool in AGENTS:
    prompt = sys.stdin.read() if not sys.stdin.isatty() else ""
    if option("--prompt-file"):
        prompt = Path(option("--prompt-file")).read_text()
    cwd = os.getcwd()
    log(prompt=prompt, cwd=cwd, cwd_mode=oct(os.stat(cwd).st_mode & 0o777),
        via_account=os.environ.get("FAKE_VIA_ACCOUNT") == "1",
        env={k: v for k, v in os.environ.items() if k.startswith("OPENCODE_")})
    if (fake_dir / f"{tool}.fails").exists():
        sys.exit(1)
    answer_file = fake_dir / f"{tool}.answer"
    answer = answer_file.read_text() if answer_file.exists() else ""
    if tool == "claude":
        try:
            print(json.dumps({"structured_output": json.loads(answer)}))
        except ValueError:
            print(json.dumps({"result": answer}))
    elif tool == "codex":
        Path(option("-o")).write_text(answer)
    else:
        print(answer)
    sys.exit(0)

# omarchy-launch-floating-terminal-with-presentation, sudo, and the rest: record only.
log()
