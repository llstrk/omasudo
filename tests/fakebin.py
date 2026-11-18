#!/usr/bin/python3
"""Stand-in for the coding agents, gum, mise and Omarchy's commands.

Linked under each tool's name in a scenario's bin folder, first on PATH. Every
call is appended to $FAKE_LOG as one JSON object; nothing reaches a real agent
or the desktop. What the scenario steers lives in $FAKE_DIR:

  accounts.json        what `omarchy-agent-account-list --json` prints
  mise-installed       tools `mise which` finds (one per line)
  gum-answers          what `gum choose` picks, one per question: an option's
                       value, its label, or the start of its label; ESC or
                       running out is Esc
  grok-home            what `omarchy-agent-account-home grok` prints
  <agent>.answer       what that agent replies (a JSON verdict or plain text)
  <agent>.verdicts     JSON {"part of a command": verdict}: per request, the
                       verdict for the first part the requested command
                       contains; others get <agent>.answer
  <agent>.fails        that agent exits 1
  <agent>.flags        models (one per line, as given to --model, "" for none)
                       on which that agent's safeguards refuse every review
  "<agent> <args>"     what that call prints, for the calls that list models
                       (`pi --list-models`, `claude --help`, ...); without
                       the file they print nothing
"""

import json
import os
import re
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


def plain(text):
    """Text as it reads on screen: colours dropped, spaces collapsed."""
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", text or "").split())


def option(name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


if tool == "gum":
    if args[:1] == ["style"]:
        log()
        print("\n".join(a for a in args[1:] if not a.startswith("--") and a not in ("rounded", "1 2", "78")))
        sys.exit(0)
    if args[:1] == ["choose"]:
        delim = option("--label-delimiter")
        rest, skip = [], False
        for a in args[1:]:
            if skip:
                skip = False
            elif a in ("--header", "--selected", "--label-delimiter", "--cursor"):
                skip = True
            else:
                rest.append(a)
        options = [a.split(delim, 1) if delim and delim in a else [a, a] for a in rest]
        # Real gum splits --selected at commas: such a label selects nothing.
        assert "," not in (option("--selected") or ""), f"gum: --selected has a comma: {option('--selected')!r}"
        labels = [plain(label) for label, _ in options]
        log(header=plain(option("--header")), selected=plain(option("--selected")) or None,
            options=labels, values=[v for _, v in options])
        queue = fake_dir / "gum-answers"
        lines = queue.read_text().splitlines() if queue.exists() else []
        if not lines or lines[0] == "ESC":
            print("nothing selected", file=sys.stderr)
            sys.exit(130)
        queue.write_text("".join(l + "\n" for l in lines[1:]))
        want = lines[0]
        hits = [v for (label, v), shown in zip(options, labels)
                if want in (v, shown) or shown.startswith(want + " ")]
        assert hits, f"gum: {want!r} is not offered: {labels}"
        print(hits[0])
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

if tool == "omarchy-agent-account-home":
    log()
    home = fake_dir / f"{args[0]}-home"
    print(home.read_text().strip() if home.exists() else "")
    sys.exit(0)

if tool == "bwrap":
    # Records the sandbox it was asked for, then runs the command without one,
    # with the environment it would have had (plus the fakes' own variables).
    log()
    env, cwd, i = {}, None, 0
    takes = {"--setenv": 2, "--bind": 2, "--ro-bind": 2, "--ro-bind-try": 2, "--symlink": 2,
             "--tmpfs": 1, "--proc": 1, "--dev": 1, "--chdir": 1}
    while args[i] != "--":
        if args[i] == "--setenv":
            env[args[i + 1]] = args[i + 2]
        elif args[i] == "--chdir":
            cwd = args[i + 1]
        i += 1 + takes.get(args[i], 0)
    env.update({k: v for k, v in os.environ.items() if k.startswith("FAKE_")}, FAKE_IN_BWRAP="1")
    if cwd:
        os.chdir(cwd)
    os.execve(args[i + 1], args[i + 1:], env)

if tool == "omarchy-agent-account-exec":
    log()
    os.execvpe(args[0], args, {**os.environ, "FAKE_VIA_ACCOUNT": "1"})

LISTINGS = (["--help"], ["--list-models"], ["models"], ["models", "--json"], ["debug", "models"],
            ["debug", "models", "--bundled"])

if tool in AGENTS and args in LISTINGS:
    log(listing=True)
    printed = fake_dir / f"{tool} {' '.join(args)}"
    if printed.exists():
        print(printed.read_text(), end="")
    sys.exit(0)

if tool in AGENTS:
    prompt = sys.stdin.read() if not sys.stdin.isatty() else ""
    if option("--prompt-file"):
        prompt = Path(option("--prompt-file")).read_text()
    cwd = os.getcwd()
    overlay = next((a.split("=", 1)[1] for a in args if a.startswith("--config=")), None)
    log(prompt=prompt, cwd=cwd, cwd_mode=oct(os.stat(cwd).st_mode & 0o777),
        via_account=os.environ.get("FAKE_VIA_ACCOUNT") == "1",
        in_bwrap=os.environ.get("FAKE_IN_BWRAP") == "1",
        overlay=Path(overlay).read_text() if overlay else None,
        env={k: v for k, v in os.environ.items()
             if k.startswith("OPENCODE_") or k in ("GROK_HOME", "PI_CODING_AGENT_DIR", "HOME")})
    if (fake_dir / f"{tool}.fails").exists():
        sys.exit(1)
    flags = fake_dir / f"{tool}.flags"
    if flags.exists() and (option("--model") or "") in flags.read_text().splitlines():
        print(json.dumps({"type": "result", "is_error": True, "stop_reason": "refusal",
                          "result": "API Error: the model's safeguards flagged this session"}))
        sys.exit(1)
    answer_file = fake_dir / f"{tool}.answer"
    answer = answer_file.read_text() if answer_file.exists() else ""
    verdicts = fake_dir / f"{tool}.verdicts"
    if verdicts.exists():
        m = re.search(r'"requesting_command": ("(?:[^"\\]|\\.)*")', prompt)
        command = json.loads(m.group(1)) if m else ""
        hit = next((v for part, v in json.loads(verdicts.read_text()).items() if part in command), None)
        if hit:
            answer = json.dumps({"verdict": hit, "summary": f"{hit} by the fake", "details": ""})
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
