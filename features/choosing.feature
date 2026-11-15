Feature: Choosing who reviews agent requests
  omasudo asks a coding agent what a root request will really do. Which agent,
  and which ones to fall back to, is the user's choice: setup lists the agents
  found on the machine and starts on Omarchy's default agent, but never picks
  one by itself.

  The steps run the real bin/omasudo in a throwaway home. Omarchy's commands,
  gum, mise and the coding agents are fakes; choosing in the picker is
  answering gum's prompts.

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

    Scenario: Every installed agent is listed, with what Omarchy knows about it
      When I run "omasudo reviewer" and press Esc
      Then the picker lists the agents:
        | agent    | status                         |
        | pi       | Omarchy default, installed     |
        | claude   | signed in                      |
        | opencode | installed                      |
        | hermes   | installed, not supported yet   |
        | codex    | not signed in                  |

    Scenario: Only supported agents can be picked
      When I run "omasudo reviewer" and press Esc
      Then the first question offers:
        | pi (Omarchy default, installed) |
        | claude (signed in)              |
        | opencode (installed)            |
        | codex (not signed in)           |
        | No AI review (show the command only) |

    Scenario: The picker starts on Omarchy's default agent
      When I run "omasudo reviewer" and press Esc
      Then the first question starts on "pi (Omarchy default, installed)"

    Scenario: An unsupported default agent is named, and the picker starts on a signed-in agent
      Given Omarchy's default agent is "hermes"
      When I run "omasudo reviewer" and press Esc
      Then the picker says "Your default agent, hermes, can't review yet; pick another."
      And the first question starts on "claude (signed in)"

    Scenario: An agent mise only declares is not listed
      Given "omp" is only a mise shim
      When I run "omasudo reviewer" and press Esc
      Then the picker does not list "omp"

  Rule: The choice is an ordered list, saved in config.json

    Scenario: A reviewer with fallbacks
      When I run "omasudo reviewer" and choose:
        | pi (Omarchy default, installed) |
        | claude (signed in)              |
        | No fallback                     |
      Then the config has the reviewers "pi, claude"
      And it prints "Reviews: pi → claude"

    Scenario: Fallbacks are asked one at a time, without the ones already chosen
      When I run "omasudo reviewer" and choose:
        | claude (signed in)              |
        | No fallback                     |
      Then the second question is "If claude can't answer, fall back to:" and offers:
        | No fallback                     |
        | pi (Omarchy default, installed) |
        | opencode (installed)            |
        | codex (not signed in)           |

    Scenario: No AI review
      When I run "omasudo reviewer" and choose:
        | No AI review (show the command only) |
      Then the config has no reviewers
      And it prints "No AI review: the dialog shows the command only."

    Scenario: Esc changes nothing
      Given the config has the reviewers "claude"
      When I run "omasudo reviewer" and press Esc
      Then the config has the reviewers "claude"
      And it prints "Nothing changed; asking again next time the shell starts."
      And it ends without an error

    Scenario: Status shows the choice
      Given the config has the reviewers "pi, claude"
      When I run "omasudo status"
      Then it prints "reviewers=pi,claude"

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
        | claude (signed in) |
        | No fallback        |
      Then setup did not offer the polkit rule
      And the config has the reviewers "claude"
