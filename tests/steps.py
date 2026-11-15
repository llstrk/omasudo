"""Step definitions for features/*.feature.

Each scenario gets a temporary folder holding:

  home/       HOME, with XDG config and state inside it
  run/        XDG_RUNTIME_DIR (reviewers' temporary folders go here)
  sysroot/    OMASUDO_SYSTEM_ROOT: where status looks for the polkit rule
  bin/        fakes (tests/fakebin.py) for gum, mise, Omarchy's commands and
              the agents a scenario installs, first on PATH
  mise/shims/ agents mise only declares

The steps run the real bin/omasudo and bin/review.py from this working tree as
separate processes. Evidence comes from this machine's real man pages and
systemctl, which are only read.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from gherkin import step

ROOT = Path(__file__).resolve().parents[1]
FAKES = Path(__file__).resolve().parent / "fakebin.py"
TOOLS = ("gum", "mise", "omarchy-agent-account-list", "omarchy-agent-account-exec",
         "omarchy-launch-floating-terminal-with-presentation", "sudo")
VERDICT_NAMES = {"NO VERDICT": "ERROR"}
STANDARD_REQUEST = "systemctl restart systemd-journald"


class Context:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="omasudo-feature."))
        self.home = self.tmp / "home"
        self.config = self.home / ".config"
        self.runtime = self.tmp / "run"
        self.sysroot = self.tmp / "sysroot"
        self.bin = self.tmp / "bin"
        self.shims = self.tmp / "mise" / "shims"
        self.fake_dir = self.tmp / "fake"
        self.log = self.fake_dir / "calls.jsonl"
        for d in (self.config, self.sysroot, self.bin, self.shims, self.fake_dir):
            d.mkdir(parents=True)
        self.runtime.mkdir(mode=0o700)
        self.log.touch()
        for name in TOOLS:
            (self.bin / name).symlink_to(FAKES)
        self.env = {
            "PATH": f"{self.bin}:{self.shims}:/usr/bin:/bin",
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_STATE_HOME": str(self.home / ".local" / "state"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "OMASUDO_SYSTEM_ROOT": str(self.sysroot),
            "FAKE_LOG": str(self.log),
            "FAKE_DIR": str(self.fake_dir),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        self.last = None       # the last command's CompletedProcess
        self.result = None     # the last review.py answer
        self.agent = None      # the agent "it" refers to
        self.scripts = {}      # script name -> path
        # A fake that cannot run would let PATH fall through to the real tool.
        for name in TOOLS:
            found = shutil.which(name, path=self.env["PATH"])
            assert found == str(self.bin / name), f"{name} resolves to {found}, not its fake"

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -------------------------------------------------------------- fakes

    def install_agent(self, name):
        link = self.bin / name
        if not link.exists():
            link.symlink_to(FAKES)

    def calls(self, tool=None):
        entries = [json.loads(line) for line in self.log.read_text().splitlines() if line]
        return [e for e in entries if tool is None or e["tool"] == tool]

    def agent_call(self, name):
        found = self.calls(name)
        assert found, f"{name} was not run"
        return found[-1]

    def config_file(self):
        return self.config / "omasudo" / "config.json"

    def read_config(self):
        try:
            return json.loads(self.config_file().read_text())
        except (OSError, ValueError):
            return {}

    def write_config(self, **changes):
        data = {**self.read_config(), **changes}
        self.config_file().parent.mkdir(parents=True, exist_ok=True)
        self.config_file().write_text(json.dumps(data))

    # -------------------------------------------------------------- running

    def run(self, command, answers=None):
        words = shlex.split(command)
        assert words[0] == "omasudo", f"not an omasudo command: {command}"
        if answers is not None:
            (self.fake_dir / "gum-answers").write_text("".join(a + "\n" for a in answers))
        self.last = subprocess.run([str(ROOT / "bin" / "omasudo"), *words[1:]], env=self.env,
                                   capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        return self.last

    def review(self, command):
        files = []
        for name, path in self.scripts.items():
            if name in command.split():
                command = " ".join(str(path) if w == name else w for w in command.split())
                files.append(str(path))
        request = {"actionId": "org.freedesktop.policykit.exec", "message": "Authentication is required",
                   "command": command, "chain": ["claude", "bash", command.split()[0]], "files": files}
        self.last = subprocess.run(["python3", "-I", str(ROOT / "bin" / "review.py"), json.dumps(request)],
                                   env=self.env, capture_output=True, text=True, timeout=120)
        assert self.last.returncode == 0, self.last.stderr
        self.result = json.loads(self.last.stdout)
        return self.result

    def output(self):
        return (self.last.stdout or "") + (self.last.stderr or "")


def table_column(ctx):
    return [row[0] for row in ctx.step.table]


def names(text):
    return [n.strip() for n in text.split(",") if n.strip()]


def request_of(ctx, agent):
    prompt = ctx.agent_call(agent)["prompt"]
    m = re.search(r"<request>\n(.*)\n</request>", prompt, re.S)
    assert m, f"{agent} got no <request> block"
    return json.loads(m.group(1))


def program(ctx, agent, name):
    progs = request_of(ctx, agent)["evidence"]["programs"]
    found = [p for p in progs if p["program"] == name]
    assert found, f"no evidence for {name}: {[p['program'] for p in progs]}"
    return found[0]


# ------------------------------------------------------------------ the machine

@step("the polkit rule is installed")
def rule_installed(ctx):
    src, root = ROOT / "system", ctx.sysroot
    places = {
        "00-subject-note.rules": "etc/polkit-1/rules.d/00-subject-note.rules",
        "polkit-subject-note": "usr/local/lib/polkit-subject-note",
        "subject-note.conf": "etc/systemd/system/polkit.service.d/subject-note.conf",
        "uninstall.sh": "usr/local/lib/omasudo/uninstall.sh",
    }
    for name, where in places.items():
        (root / where).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / name, root / where)
    digest = hashlib.sha256((src / "00-subject-note.rules").read_bytes()).hexdigest()
    (root / "usr/local/lib/omasudo/rule.sha256").write_text(digest + "\n")
    (root / "run/polkit-subject").mkdir(parents=True)


@step("these coding agents are installed:")
def agents_installed(ctx):
    accounts = []
    for agent, signed_in in ctx.step.table[1:]:
        ctx.install_agent(agent)
        if signed_in:
            accounts.append({"provider": agent, "active": "main",
                             "accounts": [{"id": "main", "signedIn": signed_in == "yes"}]})
    (ctx.fake_dir / "accounts.json").write_text(json.dumps(accounts))


@step("Omarchy's default agent is {agent}")
def default_agent(ctx, agent):
    path = ctx.config / "omarchy" / "defaults" / "agent"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(agent + "\n")


@step("{agent} is only a mise shim")
def mise_shim(ctx, agent):
    (ctx.shims / agent).symlink_to(FAKES)


@step("a script {name} containing:")
def script(ctx, name):
    path = ctx.tmp / name
    path.write_text("\n".join(table_column(ctx)) + "\n")
    ctx.scripts[name] = path


# ------------------------------------------------------------------ the config

@step("the config has the reviewers {reviewers}")
def config_reviewers(ctx, reviewers):
    if ctx.step.keyword == "Given":
        ctx.write_config(reviewers=names(reviewers))
    else:
        assert ctx.read_config().get("reviewers") == names(reviewers), ctx.read_config()


@step("the config has no reviewers")
def config_no_reviewers(ctx):
    if ctx.step.keyword == "Given":
        ctx.write_config(reviewers=[])
    else:
        assert ctx.read_config().get("reviewers") == [], ctx.read_config()


@step("the config sets {agent}'s model to {model} and effort to {effort}")
def config_model(ctx, agent, model, effort):
    agents = ctx.read_config().get("agents", {})
    agents[agent] = {"model": model, "effort": effort}
    ctx.write_config(agents=agents)


# ------------------------------------------------------------------ choosing

@step("I run {command} and press Esc")
def run_esc(ctx, command):
    ctx.run(command, answers=["ESC"])


@step("I run {command} and choose:")
def run_choose(ctx, command):
    ctx.run(command, answers=table_column(ctx))
    assert ctx.last.returncode == 0, ctx.output()


@step("I run {command}")
def run_plain(ctx, command):
    ctx.run(command)


@step("the dialog loads")
def dialog_loads(ctx):
    # What the dialog runs 3 s after it loads (see PolkitAgent.qml).
    ctx.run("omasudo setup --auto")


def listed_agents(ctx):
    out = ctx.last.stdout.splitlines()
    assert "Agents found on this machine:" in out, ctx.output()
    rows = []
    for line in out[out.index("Agents found on this machine:") + 1:]:
        if not line.strip():
            break
        name, status = line.strip().split(None, 1)
        rows.append([name, status])
    return rows


@step("the picker lists the agents:")
def picker_lists(ctx):
    assert listed_agents(ctx) == ctx.step.table[1:], listed_agents(ctx)


@step("the picker does not list {agent}")
def picker_not_listed(ctx, agent):
    assert agent not in [name for name, _ in listed_agents(ctx)], listed_agents(ctx)


@step("the picker says {text}")
def picker_says(ctx, text):
    assert text in ctx.last.stdout, ctx.output()


def questions(ctx):
    return [c for c in ctx.calls("gum") if c["args"][:1] == ["choose"]]


@step("the first question offers:")
def first_offers(ctx):
    assert questions(ctx)[0]["options"] == table_column(ctx), questions(ctx)[0]["options"]


@step("the first question starts on {label}")
def first_starts(ctx, label):
    assert questions(ctx)[0]["selected"] == label, questions(ctx)[0]


@step("the second question is {header} and offers:")
def second_question(ctx, header):
    q = questions(ctx)[1]
    assert q["header"] == header, q["header"]
    assert q["options"] == table_column(ctx), q["options"]


@step("it prints {text}")
def prints(ctx, text):
    assert text in ctx.output(), ctx.output()


@step("it ends without an error")
def ends_ok(ctx):
    assert ctx.last.returncode == 0, (ctx.last.returncode, ctx.output())


@step("a floating terminal opens {text}")
def terminal_opens(ctx, text):
    opened = [" ".join(c["args"]) for c in ctx.calls("omarchy-launch-floating-terminal-with-presentation")]
    assert any(o.endswith(text) for o in opened), opened


@step("no terminal opens")
def no_terminal(ctx):
    assert not ctx.calls("omarchy-launch-floating-terminal-with-presentation")
    assert ctx.last.returncode == 0, ctx.output()


@step("setup did not offer the polkit rule")
def rule_not_offered(ctx):
    offered = [o for q in questions(ctx) for o in q["options"]]
    assert not any(o.startswith("Set it up") for o in offered), offered
    assert "polkit rule:" not in ctx.last.stdout, ctx.output()


# ------------------------------------------------------------------ reviewing

@step("{agent} answers {verdict} {summary}")
def answers_verdict(ctx, agent, verdict, summary):
    (ctx.fake_dir / f"{agent}.answer").write_text(
        json.dumps({"verdict": verdict, "summary": summary, "details": ""}))


@step("{agent} answers {text}")
def answers_text(ctx, agent, text):
    (ctx.fake_dir / f"{agent}.answer").write_text(text)


@step("{agent} fails")
def agent_fails(ctx, agent):
    (ctx.fake_dir / f"{agent}.fails").touch()


@step("the agent asks to run {command}")
def agent_asks(ctx, command):
    ctx.review(command)


@step("the dialog shows {verdict} {summary} by {reviewer}")
def shows_verdict(ctx, verdict, summary, reviewer):
    r = ctx.result
    assert (r["verdict"], r["summary"], r["reviewer"]) == (verdict, summary, reviewer), r


@step("the dialog shows NO VERDICT {summary}")
def shows_no_verdict(ctx, summary):
    assert (ctx.result["verdict"], ctx.result["summary"]) == ("ERROR", summary), ctx.result


@step("the dialog shows no review")
def shows_nothing(ctx):
    assert ctx.result["verdict"] == "OFF", ctx.result


@step("{agent} was not asked")
def not_asked(ctx, agent):
    assert not ctx.calls(agent), ctx.calls(agent)


@step("no reviewer was asked")
def nobody_asked(ctx):
    assert not [c for c in ctx.calls() if "prompt" in c], ctx.calls()


@step("{agent} was given the man-page entry for {token} of {prog}")
def given_man_entry(ctx, agent, token, prog):
    entries = program(ctx, agent, prog)["man_entries"]
    assert token in entries and entries[token].startswith(token), list(entries)


@step("{agent} was told the man page does not document {flag}")
def told_undocumented(ctx, agent, flag):
    assert flag in program(ctx, agent, "systemctl").get("flags_not_in_man_page", [])


@step("{agent} was given the unit file of {unit}")
def given_unit(ctx, agent, unit):
    units = request_of(ctx, agent)["evidence"].get("units", [])
    found = [u for u in units if u["unit"] == unit]
    assert found and found[0]["unit_file"].startswith("# /"), units


@step("{agent} was given the contents of {name}")
def given_contents(ctx, agent, name):
    files = request_of(ctx, agent).get("files_named_in_command", [])
    text = ctx.scripts[name].read_text()
    assert any(f.get("content") == text for f in files), files


@step("{agent} was not given {text}")
def not_given(ctx, agent, text):
    assert text not in ctx.agent_call(agent)["prompt"]


@step("no reviewer had {text} in its command line")
def not_in_argv(ctx, text):
    for c in ctx.calls():
        if "prompt" in c:
            assert not any(text in a for a in c["args"]), (c["tool"], c["args"])


# ------------------------------------------------------------------ how reviewers run

@step("{agent} reviews a request")
def reviews(ctx, agent):
    ctx.agent = agent
    ctx.write_config(reviewers=[agent])
    answers_verdict(ctx, agent, "SAFE", "Restarts the journal.")
    ctx.review(STANDARD_REQUEST)
    assert ctx.result["reviewer"] == agent, ctx.result


@step("each reviewer reviews a request")
def each_reviews(ctx):
    for agent in ("claude", "codex", "grok", "pi", "omp", "opencode"):
        reviews(ctx, agent)


@step("it ran through Omarchy's account exec")
def via_account(ctx):
    assert ctx.agent_call(ctx.agent)["via_account"]
    assert [c for c in ctx.calls("omarchy-agent-account-exec") if c["args"][:1] == [ctx.agent]]


@step("it did not run through Omarchy's account exec")
def not_via_account(ctx):
    assert not ctx.agent_call(ctx.agent)["via_account"]


def contains_run(seq, part):
    return any(seq[i:i + len(part)] == part for i in range(len(seq) - len(part) + 1))


@step("it was run with:")
def run_with(ctx):
    argv = ctx.agent_call(ctx.agent)["args"]
    for cell in table_column(ctx):
        want = shlex.split(cell)
        assert contains_run(argv, want), f"{want} not in {argv}"


def claude_settings(ctx):
    argv = ctx.agent_call("claude")["args"]
    return json.loads(argv[argv.index("--settings") + 1])


@step("its settings deny reading:")
def settings_deny(ctx):
    deny = claude_settings(ctx)["permissions"]["deny"]
    for path in table_column(ctx):
        assert f"Read({path})" in deny, deny


@step("its settings turn the sandbox on with no unsandboxed escape")
def settings_sandbox(ctx):
    sb = claude_settings(ctx)["sandbox"]
    assert sb["enabled"] is True and sb["allowUnsandboxedCommands"] is False, sb


def opencode_config(ctx):
    return json.loads(ctx.agent_call("opencode")["env"]["OPENCODE_CONFIG_CONTENT"])


@step("its inline agent has every tool off and every permission denied")
def opencode_agent(ctx):
    agent = opencode_config(ctx)["agent"]["omasudo-review"]
    assert agent["tools"] == {"*": False} and agent["permission"] == {"*": "deny"}, agent


@step("its session title is not generated")
def opencode_title(ctx):
    assert opencode_config(ctx)["agent"]["title"] == {"disable": True}


@step("its database is inside the temporary folder")
def opencode_db(ctx):
    call = ctx.agent_call("opencode")
    assert Path(call["env"]["OPENCODE_DB"]).parent == Path(call["cwd"]), call["env"]


@step("it was run without the tools {tools}")
def run_without(ctx, tools):
    argv = ctx.agent_call(ctx.agent)["args"]
    removed = argv[argv.index("--disallowed-tools") + 1].split(",")
    missing = [t for t in names(tools) if t not in removed]
    assert not missing, f"not removed: {missing}"


@step("each ran in its own private folder under $XDG_RUNTIME_DIR, gone afterwards")
def private_folders(ctx):
    seen = set()
    for c in ctx.calls():
        if "prompt" not in c:
            continue
        cwd = Path(c["cwd"])
        assert cwd.parent == ctx.runtime and cwd.name.startswith("omasudo-"), cwd
        assert c["cwd_mode"] == "0o700", (c["tool"], c["cwd_mode"])
        assert not cwd.exists(), f"{cwd} was left behind"
        assert cwd not in seen, f"{cwd} was shared"
        seen.add(cwd)
    assert len(seen) == 6, seen
