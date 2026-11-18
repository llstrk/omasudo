"""Auto reasoning: the lowest of low, medium and high at which a model passes
omasudo test. The config says "effort": "auto"; omasudo test finds the level
(bin/bench.py), and every review uses the level it found. Until one is found,
or when none passes, reviews use high: the most careful level auto tries.

The test results live here too (bench.py keeps its counts in the same file).
"""
import json
import os
from pathlib import Path

RESULTS = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "omasudo" / "tests.json"
AUTO = "auto"
LADDER = ("low", "medium", "high")  # never xhigh or max: slow, and rarely needed


def load():
    try:
        data = json.loads(RESULTS.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def key(agent, model, effort):
    return f"{agent}|{model}|{effort}"


def ladder(efforts):
    """The levels auto tries, from the ones the model offers (all of LADDER
    when it lists none)."""
    return [l for l in LADDER if l in efforts] if efforts else list(LADDER)


def found(agent, model):
    """The last search's result for a model: {"level", "stable", counts...}."""
    r = load().get(key(agent, model, AUTO))
    return r if isinstance(r, dict) and r.get("level") in LADDER else None


def resolve(agent, conf, default_model=""):
    """conf with "auto" replaced by the level found for its model (or high)."""
    if conf.get("effort") != AUTO:
        return conf
    r = found(agent, conf.get("model") or default_model)
    return {**conf, "effort": r["level"] if r else LADDER[-1]}
