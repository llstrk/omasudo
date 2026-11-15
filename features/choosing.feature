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
