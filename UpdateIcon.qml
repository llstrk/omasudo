import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// The update icon: hidden while Omasudo is up to date, shown when the
// daily check (run by the dialog) found a newer version. Left click opens
// `omasudo update` in Omarchy's floating terminal; right click hides the
// icon until the next version. After omaprofile's.
//
// What to show comes from `omasudo update --status`, read again when the
// check's state file changes and every ten minutes.

BarWidget {
  id: root
  moduleName: "llstrk.omasudo"

  property bool available: false
  property string tip: ""
  readonly property string cli: decodeURIComponent(Qt.resolvedUrl("bin/omasudo").toString().replace(/^file:\/\//, ""))
  readonly property string stateFile:
    (Quickshell.env("XDG_STATE_HOME") || (Quickshell.env("HOME") || "") + "/.local/state") + "/omasudo/update.json"

  function refresh() {
    if (!statusProc.running) statusProc.running = true
  }

  visible: root.available
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: statusProc
    command: ["sh", "-c", '[ -x "$1" ] && exec "$1" update --status', "omasudo", root.cli]
    stdout: StdioCollector {
      onStreamFinished: {
        var s = {}
        try { s = JSON.parse(text) || {} } catch (e) { s = {} }
        root.available = s.icon === true
        root.tip = String(s.tooltip || "")
      }
    }
  }

  FileView {
    path: root.stateFile
    watchChanges: true
    printErrors: false
    onFileChanged: root.refresh()
  }

  Timer {
    interval: 600000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    slotSize: Style.bar.statusSlot
    tooltipText: root.tip
    onPressed: function(b) {
      if (b === Qt.RightButton) {
        root.available = false
        Quickshell.execDetached([root.cli, "update", "--dismiss"])
      } else {
        Quickshell.execDetached([root.cli, "update", "--open"])
      }
    }
  }
}
