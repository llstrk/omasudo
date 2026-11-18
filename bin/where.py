"""Whether a reviewer's model clearly runs in the cloud. omasudo test reviews
12 requests at a time on a cloud model and 2 on any other: a server on this
machine (or the LAN) answers only a few at once, and the rest wait in its
queue, using up their time.

  claude    cloud, unless ANTHROPIC_BASE_URL (environment or Claude Code's
            settings.json) points at a local address
  grok      cloud
  codex     cloud, unless config.toml picks a model_provider that is local
  pi, omp,  the model's provider: one defined in the agent's own config is
  opencode  cloud when its base URL is a public address and local when it is
            localhost, a private or LAN address; a built-in provider is cloud
            unless it runs on this machine (ollama, LM Studio, llama.cpp, ...)

A model that can't be traced to a provider, or a config that can't be read,
is not clearly cloud.
"""
import ipaddress
import json
import os
import re
import urllib.parse
from pathlib import Path

# Built-in providers that are servers on this machine, as the agents name them.
LOCAL_PROVIDERS = ("ollama", "lmstudio", "lm-studio", "llamacpp", "llama.cpp", "llama-cpp", "vllm", "localai", "jan")
LAN_SUFFIXES = (".local", ".localhost", ".lan", ".home", ".internal", ".home.arpa", ".ts.net")


def home():
    return Path(os.environ.get("HOME") or Path.home())


def config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME") or home() / ".config")


def local_url(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not host or host == "localhost" or "." not in host or host.endswith(LAN_SUFFIXES):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False  # a public host name


def provider_cloud(provider, urls):
    """urls: the providers the agent's config defines -> base URL (or None
    when it only sets options for a built-in one)."""
    url = urls.get(provider)
    if url:
        return not local_url(url)
    return not any(name in provider.lower() for name in LOCAL_PROVIDERS)


def split(model):
    provider, _, rest = model.partition("/")
    return (provider, rest) if rest else (None, model)


def read_json(path):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def claude(model):
    url = os.environ.get("ANTHROPIC_BASE_URL") or \
        (read_json(home() / ".claude" / "settings.json").get("env") or {}).get("ANTHROPIC_BASE_URL")
    return not (url and local_url(url))


def codex(model):
    import tomllib
    path = Path(os.environ.get("CODEX_HOME") or home() / ".codex") / "config.toml"
    try:
        conf = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    provider = conf.get("model_provider") or "openai"
    if provider == "openai":
        return True
    defined = conf.get("model_providers") or {}
    return provider_cloud(provider, {k: v.get("base_url") for k, v in defined.items() if isinstance(v, dict)})


def pi_like(model, settings, defined):
    """pi and omp: provider/model, or a bare model found among the defined
    providers' models; no model is the agent's own default."""
    provider, name = split(model) if model else (settings.get("provider"), settings.get("model"))
    if not name:
        return False
    if not provider:
        provider = next((p for p, d in defined.items() if name in d["models"]), None)
        if not provider:
            return False
    return provider_cloud(provider, {p: d["url"] for p, d in defined.items()})


def pi(model):
    folder = Path(os.environ.get("PI_CODING_AGENT_DIR") or home() / ".pi" / "agent")
    settings = read_json(folder / "settings.json")
    providers = read_json(folder / "models.json").get("providers") or {}
    defined = {p: {"url": d.get("baseUrl"), "models": [m.get("id") for m in d.get("models") or [] if isinstance(m, dict)]}
               for p, d in providers.items() if isinstance(d, dict)}
    return pi_like(model, {"provider": settings.get("defaultProvider"), "model": settings.get("defaultModel")},
                   defined)


def omp(model):
    try:
        import yaml
    except ImportError:
        return False
    folder = home() / ".omp" / "agent"

    def load(name):
        try:
            data = yaml.safe_load((folder / name).read_text())
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, yaml.YAMLError):
            return None
    config, models = load("config.yml"), load("models.yml")
    if config is None or models is None:
        return False
    default = (config.get("modelRoles") or {}).get("default") or ""
    provider, name = split(default)
    providers = models.get("providers") or {}
    defined = {p: {"url": d.get("baseUrl"), "models": [m.get("id") for m in d.get("models") or [] if isinstance(m, dict)]}
               for p, d in providers.items() if isinstance(d, dict)}
    return pi_like((model or "").split(":")[0], {"provider": provider, "model": name}, defined)


def opencode(model):
    folder = config_home() / "opencode"
    conf = {}
    for name in ("opencode.json", "opencode.jsonc", "config.json"):
        path = folder / name
        if path.exists():
            try:
                # jsonc: drop // and /* */ comments outside strings, and trailing commas
                text = re.sub(r'("(?:[^"\\]|\\.)*")|//[^\n]*|/\*.*?\*/', lambda m: m.group(1) or "",
                              path.read_text(), flags=re.S)
                conf = json.loads(re.sub(r",(\s*[}\]])", r"\1", text))
            except (OSError, ValueError):
                return False
            break
    provider, name = split(model or conf.get("model") or "")
    if not provider:
        return False
    defined = {p: (d.get("options") or {}).get("baseURL")
               for p, d in (conf.get("provider") or {}).items() if isinstance(d, dict)}
    return provider_cloud(provider, defined)


CHECK = {"claude": claude, "grok": lambda model: True, "codex": codex, "pi": pi, "omp": omp, "opencode": opencode}


def cloud(agent, model):
    try:
        return bool(CHECK[agent](model or ""))
    except Exception:  # anything unexpected: not clearly cloud
        return False
