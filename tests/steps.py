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
TOOLS = ("gum", "mise", "omarchy-agent-account-list", "omarchy-agent-account-exec", "omarchy-agent-account-home",
         "omarchy-launch-floating-terminal-with-presentation", "sudo", "bwrap")
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
            "PATH": f"{self.bin}:{self.home}/.local/bin:{self.shims}:/usr/bin:/bin",
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_STATE_HOME": str(self.home / ".local" / "state"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "OMASUDO_SYSTEM_ROOT": str(self.sysroot),
            "OMASUDO_BWRAP": str(self.bin / "bwrap"),
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

    def run_file(self, path, *args):
        self.last = subprocess.run([str(path), *args], env=self.env, capture_output=True, text=True,
                                   timeout=60, stdin=subprocess.DEVNULL)
        return self.last

    def command_file(self):
        return self.home / ".local" / "bin" / "omasudo"

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
        """What the terminal shows: colours dropped, spaces collapsed per line."""
        text = (self.last.stdout or "") + (self.last.stderr or "")
        return "\n".join(" ".join(line.split()) for line in re.sub(r"\x1b\[[0-9;]*[mHJ]", "", text).splitlines())


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


@step("the polkit rule is not installed")
def rule_not_installed(ctx):
    shutil.rmtree(ctx.sysroot)
    ctx.sysroot.mkdir()


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


@step("the dialog has loaded")
def dialog_loaded(ctx):
    dialog_loads(ctx)


# ------------------------------------------------------------------ the command

MARK = "# The omasudo command, written by the omasudo plugin when its dialog loads."


def write_command(ctx, checkout):
    """A command an omasudo plugin at checkout wrote."""
    ctx.command_file().parent.mkdir(parents=True, exist_ok=True)
    ctx.command_file().write_text(f"#!/bin/sh\n{MARK}\n# runs: {checkout}\nexec {shlex.quote(str(checkout))}/bin/omasudo \"$@\"\n")
    ctx.command_file().chmod(0o755)


def command_runs(ctx):
    lines = ctx.command_file().read_text().splitlines()
    assert MARK in lines, lines
    return Path(next(l for l in lines if l.startswith("# runs: "))[len("# runs: "):])


def copy_checkout(dest):
    dest.mkdir(parents=True)
    for part in ("bin", "system"):
        shutil.copytree(ROOT / part, dest / part, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "manifest.json", dest)
    return dest


@step("~/.local/bin/omasudo runs this checkout")
def command_is_here(ctx):
    assert command_runs(ctx) == ROOT, command_runs(ctx)
    ctx.run_file(ctx.command_file(), "status")
    assert ctx.last.returncode == 0 and "reviewers=" in ctx.last.stdout, ctx.output()


@step("~/.local/bin/omasudo is a script of my own")
def own_command(ctx):
    ctx.command_file().parent.mkdir(parents=True, exist_ok=True)
    ctx.command_file().write_text("#!/bin/sh\necho mine\n")
    ctx.command_file().chmod(0o755)


@step("~/.local/bin/omasudo is still my own script")
def still_own(ctx):
    assert ctx.command_file().read_text() == "#!/bin/sh\necho mine\n"


@step("~/.local/bin/omasudo runs another omasudo checkout")
def other_command(ctx):
    ctx.other = copy_checkout(ctx.tmp / "other checkout")
    write_command(ctx, ctx.other)


@step("~/.local/bin/omasudo still runs the other checkout")
def still_other(ctx):
    assert command_runs(ctx) == ctx.other, command_runs(ctx)


@step("~/.local/bin/omasudo runs an omasudo checkout that is gone")
def gone_command(ctx):
    # Written by the plugin itself, so the fallback under test is the real one.
    gone = copy_checkout(ctx.tmp / "removed checkout")
    ctx.run_file(gone / "bin" / "omasudo", "setup", "--auto")
    shutil.rmtree(gone)
    assert command_runs(ctx) == gone, command_runs(ctx)


@step("the dialog of a copy in Omarchy's plugin folder loads")
def installed_copy_loads(ctx):
    ctx.installed = copy_checkout(ctx.config / "omarchy" / "plugins" / "llstrk.omasudo")
    ctx.run_file(ctx.installed / "bin" / "omasudo", "setup", "--auto")


@step("~/.local/bin/omasudo runs that copy")
def runs_copy(ctx):
    assert command_runs(ctx) == ctx.installed, command_runs(ctx)


@step("I run the omasudo command with {args}")
def run_command(ctx, args):
    ctx.run_file(ctx.command_file(), *shlex.split(args))


@step("~/.local/bin/omasudo is still there")
def command_there(ctx):
    assert ctx.command_file().exists()


@step("~/.local/bin/omasudo is gone")
def command_gone(ctx):
    assert not ctx.command_file().exists()


@step("the picker does not list {agent}")
def picker_not_listed(ctx, agent):
    assert agent not in questions(ctx)[0]["values"], questions(ctx)[0]["values"]
    assert not re.search(rf"\b{re.escape(agent)}\b", ctx.output()), ctx.output()


@step("the picker says {text}")
def picker_says(ctx, text):
    assert text in ctx.output(), ctx.output()


def questions(ctx):
    return [c for c in ctx.calls("gum") if c["args"][:1] == ["choose"]]


@step("the first question offers:")
def first_offers(ctx):
    assert questions(ctx)[0]["options"] == table_column(ctx), questions(ctx)[0]["options"]


@step("the first question starts on {label}")
def first_starts(ctx, label):
    assert questions(ctx)[0]["selected"] == label, questions(ctx)[0]


@step("the {nth} question is {header} and offers:")
def nth_question(ctx, nth, header):
    q = questions(ctx)[["first", "second", "third"].index(nth)]
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


@step("setup offered the polkit rule")
def rule_offered(ctx):
    offered = [o for q in questions(ctx) for o in q["options"]]
    assert any(o.startswith("Set it up") for o in offered), offered


@step("the config has no choice yet")
def no_choice(ctx):
    assert "reviewers" not in ctx.read_config(), ctx.read_config()


@step("setup did not offer the polkit rule")
def rule_not_offered(ctx):
    offered = [o for q in questions(ctx) for o in q["options"]]
    assert not any(o.startswith("Set it up") for o in offered), offered
    assert "polkit rule" not in ctx.output(), ctx.output()


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


# ------------------------------------------------------------------ bubblewrap

SETTINGS = {"pi": ".pi/agent", "omp": ".omp/agent", "opencode": ".config/opencode", "grok": ".grok"}


@step("bubblewrap is not installed")
def no_bwrap(ctx):
    ctx.env["OMASUDO_BWRAP"] = ""


@step("each agent has its settings folder")
def settings_folders(ctx):
    for rel in SETTINGS.values():
        (ctx.home / rel).mkdir(parents=True, exist_ok=True)
    auth = ctx.home / ".local/share/opencode/auth.json"
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text("{}")


@step("Omarchy's active Grok account lives in {path}")
def grok_account(ctx, path):
    (ctx.fake_dir / "grok-home").write_text(str(ctx.home / path.removeprefix("~/")))
    (ctx.home / path.removeprefix("~/")).mkdir(parents=True)


def sandbox(ctx):
    found = ctx.calls("bwrap")
    assert found, "bwrap was not run"
    return found[-1]["args"]


def home_path(ctx, text):
    return str(ctx.home / text.removeprefix("~/")) if text.startswith("~/") else text


@step("it ran in bubblewrap")
def in_bwrap(ctx):
    assert ctx.agent_call(ctx.agent)["in_bwrap"]
    assert contains_run(sandbox(ctx), ["--clearenv"]) and contains_run(sandbox(ctx), ["--tmpfs", "/"])


@step("it ran without bubblewrap")
def not_in_bwrap(ctx):
    assert not ctx.agent_call(ctx.agent)["in_bwrap"]
    assert not ctx.calls("bwrap")


@step("its sandbox shows these read-only, and nothing else of the system:")
def sandbox_shows(ctx):
    args = sandbox(ctx)
    shown = {args[i + 1] for i, a in enumerate(args) if a in ("--ro-bind", "--ro-bind-try", "--bind")}
    for path in table_column(ctx):
        assert contains_run(args, ["--ro-bind-try", path, path]), f"{path} not shown read-only"
    system = {p for p in shown if not p.startswith((str(ctx.tmp), "/run/systemd/resolve", "/sys"))}
    assert system == set(table_column(ctx)), system


@step("its sandbox has {path} writable, with {hidden} emptied")
def sandbox_settings(ctx, path, hidden):
    args, path = sandbox(ctx), home_path(ctx, path)
    assert contains_run(args, ["--bind", path, path]), f"{path} not writable in {args}"
    for name in names(hidden):
        assert contains_run(args, ["--tmpfs", f"{path}/{name}"]), f"{name} not emptied"


@step("its sandbox has {path} read-only")
def sandbox_settings_ro(ctx, path):
    path = home_path(ctx, path)
    assert contains_run(sandbox(ctx), ["--ro-bind", path, path]), sandbox(ctx)


@step("its sandbox shows nothing else of the home folder")
def sandbox_home(ctx):
    args, home = sandbox(ctx), str(ctx.home)
    i = args.index(home)
    assert args[i - 2] == "--bind" and args[i - 1].startswith(str(ctx.runtime)), "home is not a throwaway folder"


@step("its environment points it at {path}")
def sandbox_env(ctx, path):
    env = ctx.agent_call(ctx.agent)["env"]
    assert home_path(ctx, path) in env.values(), env


@step("its read tool can't fetch URLs")
def omp_no_urls(ctx):
    assert ctx.agent_call("omp")["overlay"] == "fetch:\n  enabled: false\n"


@step("its inline agent may only read, list and search files")
def opencode_read_only(ctx):
    agent = opencode_config(ctx)["agent"]["omasudo-review"]
    tools = ["read", "grep", "glob", "list"]
    assert agent["tools"] == {"*": False, **{t: True for t in tools}}, agent["tools"]
    assert agent["permission"] == {"*": "deny", **{t: "allow" for t in tools}, "external_directory": "allow"}, \
        agent["permission"]


# ------------------------------------------------------------------ the real sandbox

@step("bubblewrap is really installed")
def real_bwrap(ctx):
    found = shutil.which("bwrap")
    assert found, "these steps need bubblewrap"
    ctx.env["OMASUDO_BWRAP"] = found


def expand(ctx, text):
    return home_path(ctx, text.replace("$TMP", str(ctx.tmp)).replace("$XDG_RUNTIME_DIR", str(ctx.runtime)))


@step("these files exist:")
def files_exist(ctx):
    for cell in table_column(ctx):
        path = Path(expand(ctx, cell))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("secret\n")


@step("something in {agent}'s sandbox checks:")
def look_around(ctx, agent):
    # The sandbox omasudo builds for the agent, running a shell instead of it.
    probe = r'''
for p in "$@"; do if [ -r "$p" ]; then echo "read $p"; else echo "hidden $p"; fi; done
for d in /etc /usr; do touch "$d/omasudo-probe" 2>/dev/null && echo "wrote $d"; done
echo "processes $(ls /proc | grep -c '^[0-9]')"
'''
    code = f"""
import sys, tempfile, os, subprocess
sys.path.insert(0, {str(ROOT / 'bin')!r}); import jail
with tempfile.TemporaryDirectory(prefix="omasudo-", dir=os.environ["XDG_RUNTIME_DIR"]) as wd:
    argv = jail.wrap({agent!r}, [{agent!r}], wd, {{}})
    argv = argv[:argv.index("--") + 1] + ["/bin/sh", "-c", {probe!r}, "sh", *sys.argv[1:]]
    r = subprocess.run(argv, capture_output=True, text=True)
    print(r.stdout, r.stderr, file=sys.stdout)
"""
    paths = [expand(ctx, c) for c in table_column(ctx)]
    ctx.last = subprocess.run(["python3", "-I", "-c", code, *paths], env=ctx.env,
                              capture_output=True, text=True, timeout=60)
    assert ctx.last.returncode == 0, ctx.last.stderr


@step("it could read:")
def could_read(ctx):
    for cell in table_column(ctx):
        assert f"read {expand(ctx, cell)}" in ctx.last.stdout, ctx.last.stdout


@step("it could not see:")
def could_not_see(ctx):
    for cell in table_column(ctx):
        assert f"hidden {expand(ctx, cell)}" in ctx.last.stdout, ctx.last.stdout


@step("it could not write to /etc or /usr")
def could_not_write(ctx):
    assert "wrote" not in ctx.last.stdout, ctx.last.stdout


@step("it saw only its own processes")
def own_processes(ctx):
    count = int(re.search(r"processes (\d+)", ctx.last.stdout).group(1))
    assert count < 10, ctx.last.stdout
