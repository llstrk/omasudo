"""The models and reasoning levels each agent offers, as far as it says.

  claude    model aliases and effort levels from `claude --help`
  codex     `codex debug models`: listed models, each with its levels and default
  pi        `pi --list-models`, and the thinking levels from `pi --help` for
            the models that think
  omp       `omp models --json`, each model with its levels
  opencode  `opencode models` (its variants can't be listed: no levels)
  grok      `grok models` (its effort levels can't be listed)

offer(name) -> {"models": [model], "efforts": [...]}, where a model is
{"id", "label", "efforts": [...], "default_effort"} and "efforts" are the
levels for the agent's own default model. Models is empty when the agent
lists none or could not be asked.
"""
import json
import re
import subprocess

import reviewers

TIMEOUT = 30


def run(name, *args):
    try:
        p = subprocess.run(reviewers.with_account(name, [name, *args]), capture_output=True, text=True,
                           timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def model(id, label=None, efforts=None, default_effort=None):
    # gum's --selected takes a comma-separated list, so labels have no commas.
    return {"id": id, "label": (label or id).replace(",", " "), "efforts": efforts or [], "default_effort": default_effort}


def option_help(text, flag):
    """The help text of one option, wrapped lines joined."""
    lines, found = [], False
    for line in text.splitlines():
        if re.match(rf"\s*(-\w, )?{re.escape(flag)}\b", line):
            found = True
        elif found and re.match(r"\s*-", line):
            break
        if found:
            lines.append(line.strip())
    return " ".join(lines)


def levels(text):
    """"(low, medium, high)" or "level: off, minimal, low" in an option's help."""
    m = re.search(r"\(((?:[a-z]+, )+[a-z]+)\)", text) or re.search(r":\s*((?:[a-z]+, )+[a-z]+)", text)
    return [w.strip() for w in m.group(1).split(",")] if m else []


def common(lists):
    """The levels every model takes, in the first model's order."""
    lists = [l for l in lists if l]
    return [x for x in lists[0] if all(x in l for l in lists[1:])] if lists else []


def claude():
    text = run("claude", "--help")
    aliases = re.findall(r"'([a-z][\w.-]*)'", option_help(text, "--model"))
    efforts = levels(option_help(text, "--effort"))
    return {"models": [model(a, efforts=efforts) for a in aliases], "efforts": efforts}


def codex():
    out = run("codex", "debug", "models") or run("codex", "debug", "models", "--bundled")
    try:
        listed = json.loads(out).get("models", [])
    except (ValueError, AttributeError):
        listed = []
    models = []
    for m in listed:
        if not isinstance(m, dict) or m.get("visibility", "list") != "list" or not m.get("slug"):
            continue
        efforts = [e.get("effort") for e in m.get("supported_reasoning_levels") or [] if isinstance(e, dict)]
        models.append(model(m["slug"], m.get("display_name"), [e for e in efforts if e], m.get("default_reasoning_level")))
    return {"models": models, "efforts": common([m["efforts"] for m in models])}


def pi():
    thinking = levels(option_help(run("pi", "--help"), "--thinking"))
    models = []
    for line in run("pi", "--list-models").splitlines():
        cols = line.split()
        if len(cols) < 5 or cols[0] == "provider":
            continue
        models.append(model(f"{cols[0]}/{cols[1]}", efforts=thinking if cols[4] == "yes" else []))
    return {"models": models, "efforts": thinking}


def omp():
    try:
        listed = json.loads(run("omp", "models", "--json")).get("models", [])
    except (ValueError, AttributeError):
        listed = []
    models = [model(m["selector"], efforts=m.get("thinking") if m.get("reasoning") else [])
              for m in listed if isinstance(m, dict) and m.get("selector") and m.get("kind", "chat") == "chat"]
    return {"models": models, "efforts": common([m["efforts"] for m in models])}


def opencode():
    return {"models": [model(l.strip()) for l in run("opencode", "models").splitlines() if "/" in l and " " not in l.strip()],
            "efforts": []}


def grok():
    models = []
    for line in run("grok", "models").splitlines():
        m = re.match(r"\s*[*-]\s+(\S+)(\s+\(default\))?\s*$", line)
        if m:
            models.append(model(m.group(1), m.group(1) + (" (grok's default)" if m.group(2) else "")))
    return {"models": models, "efforts": []}


OFFER = {"claude": claude, "codex": codex, "pi": pi, "omp": omp, "opencode": opencode, "grok": grok}


def offer(name):
    try:
        return OFFER[name]()
    except Exception:  # a listing that can't be read only means no choice
        return {"models": [], "efforts": []}
