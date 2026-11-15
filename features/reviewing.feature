Feature: Reviewing a request
  Each time a coding agent asks for root, the dialog runs bin/review.py with
  the request. It gathers evidence on this machine first, then asks the chosen
  reviewers in order until one answers, and the dialog shows the verdict and
  who gave it.

  The steps run the real bin/review.py with fake agents that record how they
  were run and answer what the scenario says. Evidence comes from this
  machine's real man pages.

  Background:
    Given these coding agents are installed:
      | agent  | signed in |
      | pi     |           |
      | claude | yes       |
      | codex  | yes       |

  Rule: The first reviewer that answers gives the verdict

    Scenario: The first reviewer answers
      Given the config has the reviewers "pi, claude"
      And pi answers DANGEROUS "This is not a dry run."
      When the agent asks to run "systemctl preset-all --dry-run"
      Then the dialog shows DANGEROUS "This is not a dry run." by "pi"
      And claude was not asked

    Scenario: A reviewer that can't answer is skipped
      Given the config has the reviewers "pi, claude"
      And pi fails
      And claude answers DANGEROUS "This is not a dry run."
      When the agent asks to run "systemctl preset-all --dry-run"
      Then the dialog shows DANGEROUS "This is not a dry run." by "claude"

    Scenario: An answer without a verdict counts as no answer
      Given the config has the reviewers "pi, claude"
      And pi answers "Sure, looks fine to me."
      And claude answers SAFE "Restarts Bluetooth."
      When the agent asks to run "systemctl restart bluetooth"
      Then the dialog shows SAFE "Restarts Bluetooth." by "claude"

    Scenario: A reviewer that is not installed is skipped
      Given the config has the reviewers "omp, claude"
      And claude answers SAFE "Restarts Bluetooth."
      When the agent asks to run "systemctl restart bluetooth"
      Then the dialog shows SAFE "Restarts Bluetooth." by "claude"

    Scenario: Nobody answers
      Given the config has the reviewers "pi, codex"
      And pi fails
      And codex fails
      When the agent asks to run "systemctl restart bluetooth"
      Then the dialog shows NO VERDICT "No reviewer answered (pi: exit 1; codex: exit 1); judge the command yourself."

    Scenario: No AI review
      Given the config has no reviewers
      When the agent asks to run "systemctl restart bluetooth"
      Then the dialog shows no review
      And no reviewer was asked

    Scenario: No reviewer chosen yet
      When the agent asks to run "systemctl restart bluetooth"
      Then the dialog shows NO VERDICT "No reviewer chosen yet: run omasudo reviewer."

  Rule: Reviewers get the evidence, not tools

    Scenario: The man page says what --dry-run really does
      Given the config has the reviewers "pi"
      And pi answers DANGEROUS "This is not a dry run."
      When the agent asks to run "systemctl preset-all --dry-run"
      Then pi was given the man-page entry for "--dry-run" of "systemctl"
      And pi was given the man-page entry for "preset-all" of "systemctl"

    Scenario: Flags the man page doesn't know are pointed out
      Given the config has the reviewers "pi"
      And pi answers CAUTION "Unknown flag."
      When the agent asks to run "systemctl restart bluetooth --pretend-only"
      Then pi was told the man page does not document "--pretend-only"

    Scenario: Named units come with their unit file
      Given the config has the reviewers "pi"
      And pi answers SAFE "Restarts the journal."
      When the agent asks to run "systemctl restart systemd-journald"
      Then pi was given the unit file of "systemd-journald.service"

    Scenario: A script that runs is reviewed with its contents
      Given the config has the reviewers "pi"
      And pi answers DANGEROUS "The script resets every service."
      And a script "cleanup.sh" containing:
        | #!/bin/sh                       |
        | # harmless cleanup, dry run only |
        | systemctl preset-all --dry-run  |
      When the agent asks to run "pkexec sh cleanup.sh"
      Then pi was given the contents of "cleanup.sh"
      And pi was given the man-page entry for "--dry-run" of "systemctl"

  Rule: What leaves the machine is kept to the request

    Scenario: Secrets are blanked before review
      Given the config has the reviewers "pi"
      And pi answers SAFE "Logs in."
      When the agent asks to run "mytool --password hunter2 --token=abc123 login"
      Then pi was not given "hunter2"
      And pi was not given "abc123"

    Scenario: The request goes in on stdin, never in the command line
      Given the config has the reviewers "pi, claude, codex"
      And pi fails
      And claude fails
      And codex answers SAFE "Restarts Bluetooth."
      When the agent asks to run "systemctl restart bluetooth"
      Then no reviewer had "bluetooth" in its command line

    Scenario: Text inside the request can't act as an @file mention
      Given the config has the reviewers "claude"
      And claude answers SAFE "Prints a line."
      When the agent asks to run "echo @/etc/shadow"
      Then claude was not given "@/etc/shadow"
