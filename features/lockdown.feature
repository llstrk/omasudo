Feature: How each reviewer runs
  A reviewer gets one headless turn, from an empty temporary folder, and saves
  no session where its CLI allows that. Reviewers may look further than the
  evidence omasudo gathers, but only with tools that read, and never in the
  home folder:

    Claude          read-only tools, deny rules and Claude Code's own sandbox
    pi, omp,        read, search and list files, inside a bubblewrap sandbox
    opencode, Grok  that shows system locations and the agent's own settings
    Codex           no tools, since its only way to read is a shell

  Agents with Omarchy accounts run as the account the agents panel marks
  active.

  These scenarios pin the command lines; whether each CLI honours them was
  checked against its real binary (see the PR) and is not re-run here. The
  last rule runs the real bubblewrap.

  Background:
    Given these coding agents are installed:
      | agent    | signed in |
      | claude   | yes       |
      | codex    | yes       |
      | grok     | yes       |
      | pi       |           |
      | omp      |           |
      | opencode |           |
    And each agent has its settings folder

  Rule: Claude Code and Codex lock themselves down

    Scenario: Claude Code
      When claude reviews a request
      Then it ran through Omarchy's account exec
      And it was run with:
        | -p                                 |
        | --no-session-persistence           |
        | --setting-sources ""               |
        | --strict-mcp-config                |
        | --permission-mode dontAsk          |
        | --tools Read,Grep,Glob,Bash        |
        | --model opus                       |
        | --effort low                       |
      And its settings deny reading:
        | ~/**         |
        | //proc/**    |
        | //tmp/**     |
        | //run/user/** |
        | //dev/shm/** |
      And its settings turn the sandbox on with no unsandboxed escape

    Scenario: Codex
      When codex reviews a request
      Then it ran through Omarchy's account exec
      And it was run with:
        | exec                            |
        | --ephemeral                     |
        | -s read-only                    |
        | --disable shell_tool            |
        | --disable unified_exec          |
        | --disable web_search_request    |
        | --disable standalone_web_search |
        | --disable view_image            |
        | --disable apps                  |
        | -c mcp_servers={}               |

  Rule: pi, omp, opencode and Grok read in a bubblewrap sandbox

    Scenario: The sandbox shows system locations, read-only, and an empty home folder
      When pi reviews a request
      Then it ran in bubblewrap
      And its sandbox shows these read-only, and nothing else of the system:
        | /usr            |
        | /etc            |
        | /opt            |
        | /boot           |
        | /var/lib/pacman |
      And its sandbox shows nothing else of the home folder

    Scenario: pi
      When pi reviews a request
      Then it ran in bubblewrap
      And it did not run through Omarchy's account exec
      And it was run with:
        | -p                       |
        | --no-session             |
        | --tools read,grep,find,ls |
        | --no-extensions          |
        | --no-skills              |
        | --no-mcp                 |
        | --no-context-files       |
      And its sandbox has "~/.pi/agent" writable, with "sessions" emptied
      And its environment points it at "~/.pi/agent"

    Scenario: omp
      When omp reviews a request
      Then it ran in bubblewrap
      And it was run with:
        | -p                     |
        | --no-session           |
        | --tools=read,grep,glob |
        | --no-extensions        |
        | --no-skills            |
        | --no-rules             |
        | --no-lsp               |
        | --no-pty               |
        | --no-context-files     |
      And its read tool can't fetch URLs
      And its sandbox has "~/.omp/agent" writable, with "sessions, terminal-sessions" emptied

    Scenario: opencode
      When opencode reviews a request
      Then it ran in bubblewrap
      And it was run with:
        | run                    |
        | --standalone           |
        | --agent omasudo-review |
      And its inline agent may only read, list and search files
      And its session title is not generated
      And its database is inside the temporary folder
      And its sandbox has "~/.config/opencode" read-only
      And its sandbox has "~/.local/share/opencode/auth.json" writable, with "" emptied

    Scenario: Grok
      Given Omarchy's active Grok account lives in "~/.config/omarchy/agents/grok/work"
      When grok reviews a request
      Then it ran in bubblewrap
      And it was run with:
        | --sandbox off                          |
        | --tools read_file,grep,glob,list_dir   |
        | --disable-web-search                   |
        | --no-subagents                         |
        | --no-memory                            |
        | --permission-mode dontAsk              |
      And it was run without the tools "run_terminal_cmd, task, Agent, web_search, web_fetch, write, search_replace"
      And its sandbox has "~/.config/omarchy/agents/grok/work" writable, with "sessions, logs" emptied
      And its environment points it at "~/.config/omarchy/agents/grok/work"

  Rule: Without bubblewrap, they run with their tools off

    Scenario: pi without bubblewrap
      Given bubblewrap is not installed
      When pi reviews a request
      Then it ran without bubblewrap
      And it was run with:
        | --no-tools |

    Scenario: omp without bubblewrap
      Given bubblewrap is not installed
      When omp reviews a request
      Then it ran without bubblewrap
      And it was run with:
        | --no-tools |

    Scenario: opencode without bubblewrap
      Given bubblewrap is not installed
      When opencode reviews a request
      Then it ran without bubblewrap
      And its inline agent has every tool off and every permission denied

    Scenario: Grok without bubblewrap
      Given bubblewrap is not installed
      When grok reviews a request
      Then it ran without bubblewrap
      And it ran through Omarchy's account exec
      And it was run with:
        | --sandbox workspace |
      And it was run without the tools "run_terminal_cmd, task, Agent, web_search, web_fetch, write, search_replace, read_file, grep, glob, list_dir"

  Rule: Every reviewer

    Scenario: A model and effort from the config are passed on
      Given the config sets pi's model to "local/qwen" and effort to "low"
      When pi reviews a request
      Then it was run with:
        | --model local/qwen |
        | --thinking low     |

    Scenario: Every reviewer runs in a private temporary folder
      When each reviewer reviews a request
      Then each ran in its own private folder under $XDG_RUNTIME_DIR, gone afterwards

  Rule: The sandbox, for real

    Scenario: Inside the sandbox, only system files and the agent's own settings can be read
      Given bubblewrap is really installed
      And these files exist:
        | ~/notes.txt                  |
        | ~/.ssh/id_ed25519            |
        | ~/.pi/agent/settings.json    |
        | ~/.pi/agent/sessions/s.jsonl |
        | $TMP/secret.txt              |
        | $XDG_RUNTIME_DIR/bus         |
      When something in pi's sandbox checks:
        | /etc/os-release              |
        | /usr/lib/os-release          |
        | ~/.pi/agent/settings.json    |
        | ~/notes.txt                  |
        | ~/.ssh/id_ed25519            |
        | ~/.pi/agent/sessions/s.jsonl |
        | $TMP/secret.txt              |
        | $XDG_RUNTIME_DIR/bus         |
      Then it could read:
        | /etc/os-release              |
        | /usr/lib/os-release          |
        | ~/.pi/agent/settings.json    |
      And it could not see:
        | ~/notes.txt                  |
        | ~/.ssh/id_ed25519            |
        | ~/.pi/agent/sessions/s.jsonl |
        | $TMP/secret.txt              |
        | $XDG_RUNTIME_DIR/bus         |
      And it could not write to /etc or /usr
      And it saw only its own processes
