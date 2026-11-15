"""A bubblewrap sandbox for reviewers whose CLIs can't limit what their tools read.

pi, omp, opencode and Grok get read-only file tools (read, search, list), but
none of them can stop those tools from opening ~/.ssh. So they run in a
bubblewrap sandbox that shows system locations only:

  /usr /etc /opt /boot /var/lib/pacman   visible, read-only
  your home folder                       an empty, throwaway one, with the
                                         agent's own install and settings folder
  the agent's sessions and logs          hidden (an empty folder)
  /tmp /var/tmp /run/user, processes     empty, or only the sandbox's own
  everything else                        not there

The agent's settings folder is the real one, writable, so a sign-in it
refreshes during a review is saved (a copy would lose the new token, and with
it, your sign-in). Its tools only read, so that means the reviewer can read the
agent's own settings and sign-in, but no other file of yours.

The sandbox keeps the network, since the agent has to reach its model. Its
tools can't use it: they only read files, and omp's read tool, which also
fetches URLs, runs with fetching switched off. The environment is cleared down
to what an agent needs to reach its provider.

Without bwrap, these reviewers run with their tools off instead.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

VISIBLE = ["/usr", "/etc", "/opt", "/boot", "/var/lib/pacman"]

# Provider settings and credentials an agent may take from the environment.
PASS_ENV = re.compile(
    r"^(LANG|LC_\w+|TZ|https?_proxy|HTTPS?_PROXY|no_proxy|NO_PROXY|SSL_CERT_\w+|NODE_EXTRA_CA_CERTS"
    r"|\w+_API_KEY|\w+_API_BASE|\w+_BASE_URL|\w+_ENDPOINT"
    r"|(OPENAI|ANTHROPIC|XAI|GROK|OPENROUTER|GEMINI|GOOGLE|AZURE|MISTRAL|GROQ|DEEPSEEK|OLLAMA|TOGETHER|FIREWORKS)_\w+)$")


def bwrap():
    # OMASUDO_BWRAP is for the specs: a fake, or "" for a machine without it.
    found = os.environ.get("OMASUDO_BWRAP", shutil.which("bwrap") or "")
    return found or None


def available():
    return bwrap() is not None


def binary(name):
    """The agent's real executable. mise wrappers and shims would need mise's
    own config, so they are resolved here, outside the sandbox."""
    path = shutil.which(name)
    if path and ("/mise/" in path or os.path.basename(os.path.realpath(path)) == "mise"):
        out = subprocess.run(["mise", "which", name], capture_output=True, text=True, timeout=10)
        path = out.stdout.strip() if out.returncode == 0 else None
    if not path:
        raise RuntimeError("not installed")
    return path


def install_root(exe):
    """The folder in your home the agent is installed in (mise's, ~/.bun, ...),
    shown read-only; None when it is installed system-wide."""
    try:
        rel = Path(os.path.realpath(exe)).relative_to(Path.home())
    except ValueError:
        return None
    depth = 3 if rel.parts[0] in (".local", ".config", ".cache") else 1
    return str(Path.home().joinpath(*rel.parts[:depth]))


def xdg(var, default):
    return Path(os.environ.get(var) or Path.home() / default)


def grok_home():
    if os.environ.get("GROK_HOME"):
        return Path(os.environ["GROK_HOME"])
    if shutil.which("omarchy-agent-account-home"):
        out = subprocess.run(["omarchy-agent-account-home", "grok"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    return Path.home() / ".grok"


def settings(name):
    """What the agent needs from your home: [(path, "rw" | "ro", entries to
    hide)], and environment variables that point the agent at them."""
    if name in ("pi", "omp"):
        path = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / f".{name}/agent")
        hide = ["sessions"] if name == "pi" else ["sessions", "terminal-sessions"]
        return [(path, "rw", hide)], {"PI_CODING_AGENT_DIR": str(path)}
    if name == "opencode":
        # Sessions go to a throwaway database (OPENCODE_DB), so of its data
        # folder only the sign-in is needed.
        return [(xdg("XDG_CONFIG_HOME", ".config") / "opencode", "ro", []),
                (xdg("XDG_DATA_HOME", ".local/share") / "opencode" / "auth.json", "rw", []),
                (xdg("XDG_CACHE_HOME", ".cache") / "opencode", "rw", [])], {}
    if name == "grok":
        path = grok_home()
        return [(path, "rw", ["sessions", "logs"])], {"GROK_HOME": str(path)}
    raise ValueError(name)


def wrap(name, argv, workdir, env):
    """The command line that runs argv in the sandbox, from workdir, with
    env added to the environment the sandbox keeps."""
    home = str(Path.home())
    skeleton = Path(workdir) / "home"
    skeleton.mkdir(mode=0o700)
    exe = binary(argv[0])
    installed_in = install_root(exe)
    places, pointers = settings(name)

    inner = {k: v for k, v in os.environ.items() if PASS_ENV.match(k)}
    inner.update(env)
    inner.update(pointers)
    inner.update({
        "HOME": home, "USER": os.environ.get("USER", ""), "LOGNAME": os.environ.get("USER", ""),
        "PATH": f"{os.path.dirname(exe)}:/usr/local/bin:/usr/bin",
        "XDG_CONFIG_HOME": xdg("XDG_CONFIG_HOME", ".config"), "XDG_DATA_HOME": xdg("XDG_DATA_HOME", ".local/share"),
        "XDG_CACHE_HOME": xdg("XDG_CACHE_HOME", ".cache"), "XDG_STATE_HOME": xdg("XDG_STATE_HOME", ".local/state"),
        "XDG_RUNTIME_DIR": workdir, "TMPDIR": "/tmp", "TERM": "dumb", "NO_COLOR": "1",
    })

    args = [bwrap(), "--unshare-all", "--unshare-user", "--share-net", "--disable-userns",
            "--die-with-parent", "--new-session", "--clearenv", "--tmpfs", "/"]
    for d in VISIBLE:
        args += ["--ro-bind-try", d, d]
    for link, target in (("/bin", "usr/bin"), ("/sbin", "usr/bin"), ("/lib", "usr/lib"), ("/lib64", "usr/lib")):
        args += ["--symlink", target, link]
    args += ["--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve",  # DNS
             "--ro-bind-try", "/sys", "/sys",
             "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/var/tmp",
             "--bind", str(skeleton), home]
    if installed_in:
        args += ["--ro-bind", installed_in, installed_in]
    for path, mode, hide in places:
        if not path.exists():
            continue
        args += ["--bind" if mode == "rw" else "--ro-bind", str(path), str(path)]
        for entry in hide:
            # Made first if missing, so a session the agent saves anyway lands
            # in the sandbox's empty folder, not yours.
            (path / entry).mkdir(mode=0o700, exist_ok=True)
            args += ["--tmpfs", str(path / entry)]
    args += ["--bind", workdir, workdir, "--chdir", workdir]
    for k, v in sorted(inner.items()):
        args += ["--setenv", k, str(v)]
    return args + ["--", exe, *argv[1:]]
