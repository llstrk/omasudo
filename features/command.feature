Feature: The omasudo command
  The plugin lives in Omarchy's plugin folder, so when its dialog loads it adds
  an `omasudo` command to ~/.local/bin, as omaprofile does. The command is a
  small script that runs the plugin's checkout.

  The steps run the real bin/omasudo in a throwaway home, with ~/.local/bin on
  PATH.

  Background:
    Given the polkit rule is installed
    And these coding agents are installed:
      | agent  | signed in |
      | claude | yes       |

  Rule: Loading the dialog adds the command

    Scenario: The command runs the plugin
      When the dialog loads
      Then ~/.local/bin/omasudo runs this checkout

    Scenario: It is added when setup has nothing to ask
      Given the config has the reviewers "claude"
      When the dialog loads
      Then no terminal opens
      And ~/.local/bin/omasudo runs this checkout

    Scenario: Messages name the command
      Given the dialog has loaded
      When I run "omasudo reviewer" and choose:
        | claude      |
        | No fallback |
      Then it prints "Change it any time: run omasudo"

  Rule: It never replaces what isn't its own

    Scenario: A file of your own is left alone
      Given ~/.local/bin/omasudo is a script of my own
      When the dialog loads
      Then ~/.local/bin/omasudo is still my own script

    Scenario: Another checkout keeps its command
      Given ~/.local/bin/omasudo runs another omasudo checkout
      When the dialog loads
      Then ~/.local/bin/omasudo still runs the other checkout

    Scenario: A command whose checkout is gone is taken over
      Given ~/.local/bin/omasudo runs an omasudo checkout that is gone
      When the dialog loads
      Then ~/.local/bin/omasudo runs this checkout

    Scenario: The plugin Omarchy installed takes over from another checkout
      Given ~/.local/bin/omasudo runs another omasudo checkout
      When the dialog of a copy in Omarchy's plugin folder loads
      Then ~/.local/bin/omasudo runs that copy

  Rule: After the plugin is removed, the command says what is left

    Scenario: The polkit rule is still installed
      Given ~/.local/bin/omasudo runs an omasudo checkout that is gone
      When I run the omasudo command with "reviewer"
      Then it prints "omasudo was removed, but its polkit rule is still installed."
      And ~/.local/bin/omasudo is still there

    Scenario: Nothing is left
      Given the polkit rule is not installed
      And ~/.local/bin/omasudo runs an omasudo checkout that is gone
      When I run the omasudo command with "reviewer"
      Then it prints "omasudo was removed; removing this command too."
      And ~/.local/bin/omasudo is gone
