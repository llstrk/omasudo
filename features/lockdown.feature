Feature: How each reviewer runs
  A reviewer gets one headless turn, from an empty temporary folder, and saves
  no session where its CLI allows that. Everyone but Claude runs with tools
  switched off or denied; Claude keeps read-only tools that cannot read the
  home folder. Agents with Omarchy accounts run as the account the agents
  panel marks active.

  These scenarios pin the command lines; whether each CLI honours them was
  checked against its real binary (see the PR) and is not re-run here.

  Background:
    Given these coding agents are installed:
      | agent    | signed in |
      | claude   | yes       |
      | codex    | yes       |
      | grok     | yes       |
      | pi       |           |
      | omp      |           |
      | opencode |           |

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

  Scenario: pi
    When pi reviews a request
    Then it did not run through Omarchy's account exec
    And it was run with:
      | -p                  |
      | --no-session        |
      | --no-tools          |
      | --no-extensions     |
      | --no-skills         |
      | --no-mcp            |
      | --no-context-files  |

  Scenario: omp
    When omp reviews a request
    Then it was run with:
      | -p                  |
      | --no-session        |
      | --no-tools          |
      | --no-extensions     |
      | --no-skills         |
      | --no-rules          |
      | --no-lsp            |
      | --no-pty            |
      | --no-context-files  |

  Scenario: opencode
    When opencode reviews a request
    Then it was run with:
      | run                    |
      | --standalone           |
      | --agent omasudo-review |
    And its inline agent has every tool off and every permission denied
    And its session title is not generated
    And its database is inside the temporary folder

  Scenario: Grok
    When grok reviews a request
    Then it ran through Omarchy's account exec
    And it was run with:
      | --sandbox workspace    |
      | --disable-web-search   |
      | --no-subagents         |
      | --no-memory            |
      | --permission-mode dontAsk |
    And it was run without the tools "run_terminal_cmd, task, Agent, web_search, web_fetch, write, search_replace, read_file, grep, glob, list_dir"

  Scenario: A model and effort from the config are passed on
    Given the config sets pi's model to "local/qwen" and effort to "low"
    When pi reviews a request
    Then it was run with:
      | --model local/qwen |
      | --thinking low     |

  Scenario: Every reviewer runs in a private temporary folder
    When each reviewer reviews a request
    Then each ran in its own private folder under $XDG_RUNTIME_DIR, gone afterwards
