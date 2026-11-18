Feature: Choosing who reviews agent requests
  omasudo asks a coding agent what a root request will really do. Which agent,
  and which ones to fall back to, is the user's choice: setup lists the agents
  found on the machine and starts on Omarchy's default agent, but never picks
  one by itself.

  The steps run the real bin/omasudo in a throwaway home. Omarchy's commands,
  gum, mise and the coding agents are fakes; choosing in the picker is
  answering gum's prompts. Options read as they do on screen, without colour:
  "●" is ready to use, "○" is not signed in.

  Background:
    Given the polkit rule is installed
    And these coding agents are installed:
      | agent    | signed in |
      | pi       |           |
      | claude   | yes       |
      | codex    | no        |
      | opencode |           |
      | hermes   |           |
    And Omarchy's default agent is "pi"

  Rule: The picker lists what is on this machine

    Scenario: Every supported agent can be picked, with what Omarchy knows about it
      When I run "omasudo reviewer" and press Esc
      Then the first question offers:
        | pi ● installed Omarchy default     |
        | claude ● signed in                 |
        | opencode ● installed               |
        | codex ○ not signed in              |
        | No AI review just show the command |

    Scenario: Installed agents that can't review are named
      When I run "omasudo reviewer" and press Esc
      Then the picker says "Also installed, not supported yet: hermes"

    Scenario: The picker starts on Omarchy's default agent
      When I run "omasudo reviewer" and press Esc
      Then the first question starts on "pi ● installed Omarchy default"

    Scenario: An unsupported default agent is named, and the picker starts on a signed-in agent
      Given Omarchy's default agent is "hermes"
      When I run "omasudo reviewer" and press Esc
      Then the picker says "Your default agent, hermes, can't review yet."
      And the first question starts on "claude ● signed in"

    Scenario: An agent mise only declares is not listed
      Given "omp" is only a mise shim
      When I run "omasudo reviewer" and press Esc
      Then the picker does not list "omp"

  Rule: The choice is an ordered list, saved in config.json

    Scenario: A reviewer with fallbacks
      When I run "omasudo reviewer" and choose:
        | pi     |
        | claude |
        | Done   |
      Then the config has the reviewers "pi, claude"
      And it prints "Reviews pi → claude"

    Scenario: After the first fallback, the list ends with "Done"
      When I run "omasudo reviewer" and choose:
        | pi     |
        | claude |
        | Done   |
      Then the second question is "If pi can't answer, fall back to" and offers:
        | No fallback           |
        | claude ● signed in    |
        | opencode ● installed  |
        | codex ○ not signed in |
      And the third question is "If claude can't answer, fall back to" and offers:
        | Done                  |
        | opencode ● installed  |
        | codex ○ not signed in |

    Scenario: Fallbacks are asked one at a time, without the ones already chosen
      When I run "omasudo reviewer" and choose:
        | claude      |
        | No fallback |
      Then the second question is "If claude can't answer, fall back to" and offers:
        | No fallback                    |
        | pi ● installed Omarchy default |
        | opencode ● installed           |
        | codex ○ not signed in          |

    Scenario: No AI review
      When I run "omasudo reviewer" and choose:
        | No AI review |
      Then the config has no reviewers
      And it prints "No AI review: the dialog shows the command only."

    Scenario: Esc changes nothing
      Given the config has the reviewers "claude"
      When I run "omasudo reviewer" and press Esc
      Then the config has the reviewers "claude"
      And it prints "Nothing changed."
      And it ends without an error

    Scenario: Esc before anything is chosen asks again later
      When I run "omasudo reviewer" and press Esc
      Then the config has no choice yet
      And it prints "Nothing changed; asking again next time the shell starts."

    Scenario: Status shows the choice
      Given the config has the reviewers "pi, claude"
      When I run "omasudo status"
      Then it prints "reviewers=pi,claude"

  Rule: After each agent, its model and reasoning level, as far as the agent lists them

    Scenario: Claude's models and levels, with omasudo's own defaults first
      Given "claude --help" prints:
        | --effort <level>  Effort level for the session (low, high, max)     |
        | --model <model>   Model for the session: an alias ('opus' or 'sonnet') |
      When I run "omasudo reviewer" and choose:
        | claude      |
        | sonnet      |
        | high        |
        | No fallback |
      Then the second question is "Model for claude" and offers:
        | Default opus |
        | opus         |
        | sonnet       |
      And the third question is "Reasoning for claude · sonnet" and offers:
        | Default low |
        | low         |
        | high        |
        | max         |
      And the config sets claude's model to "sonnet" and effort to "high"
      And it prints "claude sonnet, high"

    Scenario: "Default" leaves the choice to the agent
      Given "claude --help" prints:
        | --effort <level>  Effort level for the session (low, high, max)     |
        | --model <model>   Model for the session: an alias ('opus' or 'sonnet') |
      And the config sets claude's model to "sonnet" and effort to "max"
      When I run "omasudo reviewer" and choose:
        | claude      |
        | Default     |
        | Default     |
        | No fallback |
      Then the config has no settings for claude

    Scenario: The screens start on the current model and level
      Given "claude --help" prints:
        | --effort <level>  Effort level for the session (low, high, max)     |
        | --model <model>   Model for the session: an alias ('opus' or 'sonnet') |
      And the config sets claude's model to "sonnet" and effort to "max"
      When I run "omasudo reviewer" and choose:
        | claude |
        | sonnet |
      Then the second question starts on "sonnet"
      And the third question starts on "max"

    Scenario: Esc on the model screen keeps what was set
      Given "claude --help" prints:
        | --effort <level>  Effort level for the session (low, high, max)     |
        | --model <model>   Model for the session: an alias ('opus' or 'sonnet') |
      And the config sets claude's model to "sonnet" and effort to "max"
      When I run "omasudo reviewer" and choose:
        | claude |
        | ESC    |
      Then the config sets claude's model to "sonnet" and effort to "max"
      And the config has the reviewers "claude"

    Scenario: Each Codex model has its own levels, and hidden models are not listed
      Given "codex debug models" prints:
        | {"models": [{"slug": "gpt-a", "display_name": "GPT A", "visibility": "list", "default_reasoning_level": "medium", "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}]}, {"slug": "gpt-secret", "visibility": "hide", "supported_reasoning_levels": []}]} |
      When I run "omasudo reviewer" and choose:
        | codex       |
        | gpt-a       |
        | low         |
        | No fallback |
      Then the second question is "Model for codex" and offers:
        | Default codex's own default |
        | GPT A gpt-a                 |
      And the third question is "Reasoning for codex · gpt-a" and offers:
        | Default medium |
        | low            |
        | medium         |
      And the config sets codex's model to "gpt-a" and effort to "low"

    Scenario: A pi model that doesn't think has no reasoning screen
      Given "pi --list-models" prints:
        | provider  model  context  max-out  thinking  images |
        | local     think  128K     32K      yes       no     |
        | local     fast   128K     32K      no        no     |
      And "pi --help" prints:
        | --thinking <level>  Set thinking level: off, low, high |
      When I run "omasudo reviewer" and choose:
        | pi          |
        | local/fast  |
        | No fallback |
      Then the second question is "Model for pi"
      And the third question is "If pi can't answer, fall back to"
      And the config sets pi's model to "local/fast" only

    Scenario: A fallback gets its own model screen
      Given "claude --help" prints:
        | --model <model>   Model for the session: an alias ('opus' or 'sonnet') |
      When I run "omasudo reviewer" and choose:
        | pi     |
        | claude |
        | sonnet |
        | Done   |
      Then the third question is "Model for claude"
      And the config sets claude's model to "sonnet" only

    Scenario: An agent that lists no models goes straight on
      When I run "omasudo reviewer" and choose:
        | opencode    |
        | No fallback |
      Then the second question is "If opencode can't answer, fall back to"
      And the config has the reviewers "opencode"

  Rule: Running omasudo opens setup

    Scenario: The picker opens on the current reviewer
      Given the config has the reviewers "claude, pi"
      When I run "omasudo" and press Esc
      Then the first question starts on "claude ● signed in"
      And setup did not offer the polkit rule

    Scenario: After "No AI review", it opens there
      Given the config has no reviewers
      When I run "omasudo" and press Esc
      Then the first question starts on "No AI review just show the command"

    Scenario: Without the polkit rule, it is offered first
      Given the polkit rule is not installed
      When I run "omasudo" and choose:
        | Not now     |
        | claude      |
        | No fallback |
      Then setup offered the polkit rule
      And the config has the reviewers "claude"

    Scenario: The picker says the polkit rule was installed
      Given the polkit rule is not installed
      When I run "omasudo" and choose:
        | Set it up   |
        | claude      |
        | No fallback |
      Then the picker says "✓ Polkit rule installed"

    Scenario: The picker says how to set up the polkit rule later
      Given the polkit rule is not installed
      When I run "omasudo" and choose:
        | Don't ask again |
        | claude          |
        | No fallback     |
      Then the picker says "No polkit rule. To set it up later, run"

  Rule: Setup asks once, when the dialog loads and nothing is chosen yet

    Scenario: Nothing chosen yet
      When the dialog loads
      Then a floating terminal opens "omasudo setup --prompted"

    Scenario: Already chosen
      Given the config has the reviewers "claude"
      When the dialog loads
      Then no terminal opens

    Scenario: "No AI review" counts as a choice
      Given the config has no reviewers
      When the dialog loads
      Then no terminal opens

    Scenario: With the rule installed, setup goes straight to the picker
      When I run "omasudo setup --prompted" and choose:
        | claude      |
        | No fallback |
      Then setup did not offer the polkit rule
      And the config has the reviewers "claude"
