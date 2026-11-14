import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Polkit
import Quickshell.Wayland
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "PolkitModel.js" as PolkitModel

Item {
  id: root

  property string fontFamily: Style.font.menuFamily
  // Bound to the central [polkit] section in shell.toml via Commons.Color.qml.
  property color accent: Commons.Color.polkit.accent
  property color background: Commons.Color.polkit.background
  property color foreground: Commons.Color.polkit.text
  property color border: Commons.Color.polkit.border
  property color borderError: Commons.Color.polkit.borderError
  property var borderSpec: Border.surfaceSpec("polkit", errorFlash ? "border-error" : "border", errorFlash ? borderError : border, Math.max(1, Style.space(2)), "border-alpha")
  property color scrim: Commons.Color.polkit.scrim
  readonly property int cornerRadius: Style.cornerRadius
  property int contentMargin: Style.spacing.panelPadding
  property int fieldHeight: Math.max(Style.space(42), Style.spacing.controlHeight)

  property bool closing: false
  property bool submitted: false
  property string currentMessage: ""
  property string currentPrompt: ""
  property string currentSupplementary: ""
  property bool responseRequired: false
  property bool responseVisible: false
  property bool failed: false
  property bool errorFlash: false
  // pam_fprintd appears in the polkit PAM stack (a sensor is enrolled).
  property bool fingerprintConfigured: false
  // Lid shut right now — the reader is physically unreachable, so we fall back
  // to the password even when a sensor is enrolled. Refreshed per request.
  property bool laptopClosed: false
  property int shakeOffset: 0

  // The agent is created from agentComponent, and created again when polkitd
  // restarts (a restart drops every agent's registration).
  property var polkitAgent: null
  property int agentGeneration: 0
  property string polkitdPid: ""
  readonly property bool agentActive: !!(polkitAgent && polkitAgent.isActive)
  readonly property var agentFlow: polkitAgent ? polkitAgent.flow : null

  readonly property bool dialogVisible: agentActive || closing
  // We show one method at a time. Fingerprint owns the dialog while PAM is
  // waiting on the reader (lid open, sensor enrolled); the moment PAM asks for
  // a password — including immediately when the lid is shut and the clamshell
  // gate skips pam_fprintd — we switch to the password field instead.
  readonly property bool fingerprintMode: fingerprintConfigured && !laptopClosed && dialogVisible && !responseRequired && !submitted && !errorFlash
  readonly property int cardHeight: panel.height > 0 ? Math.min(fieldHeight + contentMargin * 2, panel.height - Style.gapsOut * 2) : fieldHeight + contentMargin * 2
  // Password mode is a wide field; fingerprint mode collapses to a square that
  // just frames the centered sensor icon.
  readonly property int cardWidth: fingerprintMode ? cardHeight : Math.min(Style.space(312), Math.max(Style.space(260), panel.width - Style.gapsOut * 2))

  // --- Requester + review (omasudo additions) ---------------------------
  // The command line and verdict live only in memory: never console.log them,
  // since omarchy-shell output goes to the journal.
  readonly property string binDir: decodeURIComponent(Qt.resolvedUrl("bin").toString().replace(/^file:\/\//, ""))
  property var request: null      // bin/request-info.py output
  property string reviewState: "" // "", "running", "done"
  property var review: null       // bin/review.py output (+ cachedAt when reused)
  property int reviewSeconds: 0
  property string currentKey: ""  // cache key of the request on screen

  // Verdicts by request key (action + argv + named file contents), memory only.
  // Reviews outlive the dialog (review.py caps them at 90s) so an agent's retry
  // of the same command gets the verdict instantly; no notification is sent.
  readonly property int cacheTtlMs: 10 * 60 * 1000
  readonly property int maxPendingReviews: 3
  property var reviewCache: ({})   // key -> {verdict, summary, details, command, at}
  property var pendingReviews: ({}) // key -> start time (ms)

  Timer {
    interval: 1000
    repeat: true
    running: root.reviewState === "running"
    onTriggered: {
      var started = root.pendingReviews[root.currentKey]
      root.reviewSeconds = started ? Math.floor((Date.now() - started) / 1000) : root.reviewSeconds + 1
    }
  }
  readonly property int infoWidth: Math.min(Style.space(640), panel.width - Style.gapsOut * 2)
  readonly property color verdictColor: {
    if (reviewState !== "done" || !review) return foreground
    if (review.verdict === "DANGEROUS") return Commons.Color.polkit.textError
    if (review.verdict === "CAUTION") return "#d4a73f"
    if (review.verdict === "SAFE") return accent
    return Commons.Color.muted
  }

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  // Bumped whenever the dialog's request changes or closes, so a lookup that
  // finishes late knows it is no longer the one on screen.
  property int inspectionToken: 0

  function startInspection() {
    stopInspection()
    var flow = root.agentFlow
    if (!flow) return
    // Snapshot what the review needs: the flow may be gone by the time the
    // lookup returns (e.g. cancelled within a second), and the review should
    // still run so its verdict is cached and notified.
    var job = infoJob.createObject(root, {
      token: inspectionToken,
      actionId: String(flow.actionId || ""),
      message: currentMessage,
      command: ["python3", "-I", binDir + "/request-info.py", String(flow.actionId || "")]
    })
    job.running = true
  }

  // Clears what the dialog shows. Lookups and reviews keep going (see reviewCache).
  function stopInspection() {
    inspectionToken++
    request = null
    review = null
    reviewState = ""
    currentKey = ""
  }

  function freshCached(key) {
    var hit = reviewCache[key]
    return hit && Date.now() - hit.at < cacheTtlMs ? hit : null
  }

  function pruneCache() {
    var next = ({})
    var now = Date.now()
    for (var k in reviewCache) if (now - reviewCache[k].at < cacheTtlMs) next[k] = reviewCache[k]
    reviewCache = next
  }

  function handleRequestInfo(lookup, text) {
    // onScreen: this lookup still belongs to the open dialog. If not, only
    // start (or skip) the review; finishReview notifies when it completes.
    var onScreen = agentActive && lookup.token === inspectionToken
    var info
    try { info = JSON.parse(text) } catch (e) { info = { found: false } }
    if (onScreen) request = info
    if (!info.found || !info.agent || !info.key) return
    if (onScreen) currentKey = info.key

    var hit = freshCached(info.key)
    if (hit) {
      if (onScreen) {
        review = Object.assign({ cachedAt: hit.at }, hit)
        reviewState = "done"
      }
      return
    }
    if (onScreen) {
      reviewSeconds = 0
      reviewState = "running"
    }
    if (pendingReviews[info.key]) return  // same command already under review: wait for it
    if (Object.keys(pendingReviews).length >= maxPendingReviews) {
      if (onScreen) {
        review = { verdict: "ERROR", summary: strings.t("review.busy"), details: "" }
        reviewState = "done"
      }
      return
    }

    var job = reviewJob.createObject(root, {
      key: info.key,
      command: ["python3", "-I", binDir + "/review.py", JSON.stringify({
        actionId: lookup.actionId,
        message: lookup.message,
        command: info.command,
        parentCommand: info.parentCommand,
        chain: info.chain,
        files: info.files || []
      })]
    })
    var pending = Object.assign({}, pendingReviews)
    pending[info.key] = Date.now()
    pendingReviews = pending
    job.running = true
  }

  function finishReview(key, text, exitCode) {
    var pending = Object.assign({}, pendingReviews)
    delete pending[key]
    pendingReviews = pending

    var r = null
    try { r = JSON.parse(text) } catch (e) {}
    var ok = exitCode === 0 && r && r.verdict !== "ERROR" && r.verdict !== "OFF"
    if (ok) {
      pruneCache()
      var cache = Object.assign({}, reviewCache)
      cache[key] = { verdict: r.verdict, summary: r.summary, details: r.details, command: r.command, reviewer: r.reviewer, at: Date.now() }
      reviewCache = cache
    }

    if (agentActive && currentKey === key && reviewState === "running") {
      if (r && r.verdict === "OFF") {  // no AI review chosen: show the command only
        review = null
        reviewState = ""
        return
      }
      review = ok ? r : { verdict: "ERROR", summary: (r && r.verdict === "ERROR" && r.summary) || strings.t("review.error"), details: "" }
      reviewState = "done"
    }
  }

  Component {
    id: reviewJob
    Process {
      id: job
      property string key: ""
      stdout: StdioCollector { id: jobOut; waitForEnd: true }
      onExited: function(exitCode) {
        root.finishReview(job.key, jobOut.text, exitCode)
        job.destroy()
      }
    }
  }

  Component {
    id: infoJob
    Process {
      id: lookup
      property int token: -1
      property string actionId: ""
      property string message: ""
      stdout: StdioCollector { id: lookupOut; waitForEnd: true }
      onExited: function(exitCode) {
        if (exitCode === 0) root.handleRequestInfo(lookup, lookupOut.text)
        lookup.destroy()
      }
    }
  }

  // ---------------------------------------------------------------------------

  function authorizationLabel(message) {
    return message ? PolkitModel.authorizationLabel(message, I18n.t) : I18n.t("polkit.authenticationNeeded")
  }

  function loadPamConfig(raw) {
    fingerprintConfigured = PolkitModel.fingerprintConfiguredFromPamConfig(raw)
  }

  function refreshLidState() {
    if (!laptopClosedProc.running) laptopClosedProc.running = true
  }

  function resetSnapshot() {
    currentMessage = ""
    currentPrompt = ""
    currentSupplementary = ""
    responseRequired = false
    responseVisible = false
    failed = false
    errorFlash = false
    submitted = false
    passwordInput.text = ""
    stopInspection()
  }

  function syncFromFlow() {
    var flow = root.agentFlow
    if (!flow) return

    currentMessage = String(flow.message || "")
    currentPrompt = String(flow.inputPrompt || "")
    currentSupplementary = String(flow.supplementaryMessage || "")
    responseRequired = !!flow.isResponseRequired
    responseVisible = !!flow.responseVisible
    failed = !!flow.failed

    if (responseRequired) submitted = false
  }

  function beginFlow() {
    closeTimer.stop()
    closing = false
    submitted = false
    passwordInput.text = ""
    refreshLidState()
    syncFromFlow()
    startInspection()
    Qt.callLater(refocus)
  }

  function refocus() {
    if (!dialogVisible) return
    // In fingerprint mode there is no field to type into — park focus on the
    // key catcher so Escape still cancels; otherwise focus the password field.
    if (fingerprintMode) keyCatcher.forceActiveFocus()
    else passwordInput.forceActiveFocus()
  }

  function submitResponse() {
    var flow = root.agentFlow
    if (!flow || !flow.isResponseRequired) return
    submitted = true
    errorFlash = false
    flow.submit(passwordInput.text)
    passwordInput.text = ""
    keyCatcher.forceActiveFocus()
  }

  function cancelRequest() {
    var flow = root.agentFlow
    passwordInput.text = ""
    submitted = false
    closing = true
    closeTimer.restart()
    if (flow) flow.cancelAuthenticationRequest()
  }

  function triggerFailureFeedback() {
    submitted = false
    errorFlash = true
    passwordInput.text = ""
    errorTimer.restart()
    shakeAnimation.restart()
    Qt.callLater(refocus)
  }

  Timer {
    id: closeTimer
    interval: 300
    repeat: false
    onTriggered: {
      closing = false
      resetSnapshot()
    }
  }

  Timer {
    id: errorTimer
    interval: 1200
    repeat: false
    onTriggered: root.errorFlash = false
  }

  SequentialAnimation {
    id: shakeAnimation
    NumberAnimation { target: root; property: "shakeOffset"; to: -8; duration: Style.duration(35); easing.type: Easing.OutQuad }
    NumberAnimation { target: root; property: "shakeOffset"; to: 8; duration: Style.duration(50); easing.type: Easing.InOutQuad }
    NumberAnimation { target: root; property: "shakeOffset"; to: 0; duration: Style.duration(55); easing.type: Easing.OutQuad }
  }
  FileView {
    path: "/etc/pam.d/polkit-1"
    watchChanges: true
    printErrors: false
    onLoaded: root.loadPamConfig(text())
    onLoadFailed: root.fingerprintConfigured = false
    onFileChanged: reload()
  }

  Process {
    id: laptopClosedProc
    command: ["bash", "-c", "omarchy-hw-laptop-closed && echo closed || echo open"]
    stdout: StdioCollector { id: laptopClosedOut; waitForEnd: true }
    onExited: root.laptopClosed = String(laptopClosedOut.text || "").trim() === "closed"
  }

  // --- Agent lifecycle and setup (omasudo additions) -------------------
  readonly property string pluginDir: decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")).replace(/\/$/, "")

  function createAgent() {
    if (polkitAgent) return
    // A new path per generation: the old object's unregister call (on destroy)
    // must not match the new registration.
    polkitAgent = agentComponent.createObject(root, {
      path: "/org/omarchy/PolkitAgent" + (agentGeneration ? "_" + agentGeneration : "")
    })
  }

  function reregisterAgent() {
    if (agentActive) return  // never pull a live request; the next poll retries
    if (polkitAgent) polkitAgent.destroy()
    polkitAgent = null
    agentGeneration++
    recreateTimer.restart()
  }

  Component.onCompleted: createAgent()

  Timer {
    id: recreateTimer
    interval: 500  // after the old object is gone
    onTriggered: root.createAgent()
  }

  // polkitd forgets agents when it restarts (an update, or system/install.sh).
  // Watch its PID and register again when it changes.
  Timer {
    interval: 5000
    running: true
    repeat: true
    onTriggered: if (!polkitdPidProc.running) polkitdPidProc.running = true
  }

  Process {
    id: polkitdPidProc
    command: ["systemctl", "show", "polkit.service", "-p", "MainPID", "--value"]
    stdout: StdioCollector { id: polkitdPidOut; waitForEnd: true }
    onExited: {
      var pid = String(polkitdPidOut.text || "").trim()
      if (!pid || pid === "0") return
      var changed = root.polkitdPid !== "" && pid !== root.polkitdPid
      if (changed && root.agentActive) return  // keep the old PID; retry next poll
      root.polkitdPid = pid
      if (changed) root.reregisterAgent()
    }
  }

  // First run: offer to install the polkit rule (bin/omasudo decides
  // whether to ask, in a floating terminal).
  Timer {
    interval: 3000
    running: true
    onTriggered: Quickshell.execDetached(["sh", "-c",
      '[ -x "$1" ] || exit 0; "$1" update --after-load; exec "$1" setup --auto',
      "omasudo", root.pluginDir + "/bin/omasudo"])
  }

  // Update check: a minute after loading, then hourly. bin/update.py fetches
  // at most once a day and notifies once per new version.
  function checkForUpdate() {
    Quickshell.execDetached(["sh", "-c", '[ -x "$1" ] && exec "$1" update --scheduled',
                             "omasudo", root.pluginDir + "/bin/omasudo"])
  }
  Timer { interval: 60000; running: true; onTriggered: root.checkForUpdate() }
  Timer { interval: 3600000; running: true; repeat: true; onTriggered: root.checkForUpdate() }

  // `omarchy plugin remove` disables the plugin (destroying this) and then
  // deletes its folder. If the folder goes while the rule is still installed,
  // offer to remove the rule, using the root-owned copy of the uninstaller.
  readonly property string removalWatchScript: [
    'u=/usr/local/lib/omasudo/uninstall.sh',
    'i=0',
    'while [ $i -lt 20 ]; do',
    '  if [ ! -e "$1/manifest.json" ]; then',
    '    [ -x "$u" ] || exit 0',
    '    exec omarchy-launch-floating-terminal-with-presentation "gum confirm \'Omasudo was removed. Remove its polkit rule too?\' && sudo $u"',
    '  fi',
    '  sleep 0.5; i=$((i + 1))',
    'done'
  ].join("\n")
  property string watchDir: pluginDir
  Component.onDestruction: {
    if (root.watchDir)
      Quickshell.execDetached(["sh", "-c", root.removalWatchScript, "omasudo-removal-watch", root.watchDir])
  }

  Component {
    id: agentComponent
    PolkitAgent {
      onAuthenticationRequestStarted: root.beginFlow()
      onIsActiveChanged: {
        if (isActive) root.syncFromFlow()
        else if (!root.closing) root.resetSnapshot()
      }
      onIsRegisteredChanged: {
        if (isRegistered) console.log("omarchy polkit agent registered")
        else console.warn("omarchy polkit agent is not registered; another agent may be running")
      }
    }
  }

  Connections {
    target: root.agentFlow

    function onIsResponseRequiredChanged() {
      root.syncFromFlow()
      if (!root.agentFlow || !root.agentFlow.isResponseRequired) passwordInput.text = ""
      Qt.callLater(root.refocus)
    }

    function onInputPromptChanged() { root.syncFromFlow() }
    function onResponseVisibleChanged() { root.syncFromFlow() }
    function onSupplementaryMessageChanged() { root.syncFromFlow() }
    function onFailedChanged() { root.syncFromFlow() }

    function onAuthenticationFailed() {
      root.syncFromFlow()
      root.triggerFailureFeedback()
    }

    function onAuthenticationSucceeded() {
      root.closing = true
      closeTimer.restart()
    }

    function onAuthenticationRequestCancelled() {
      root.closing = true
      closeTimer.restart()
    }
  }

  PanelWindow {
    id: panel
    // Right-to-left languages read this window mirrored.
    Binding { target: panel.contentItem; property: "LayoutMirroring.enabled"; value: Commons.I18n.rightToLeft }
    Binding { target: panel.contentItem; property: "LayoutMirroring.childrenInherit"; value: true }

    visible: root.dialogVisible
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omarchy-polkit"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.refocus()
    }

    BorderSurface {
      id: card
      width: root.cardWidth
      height: root.cardHeight
      radius: root.cornerRadius
      anchors.centerIn: parent
      anchors.horizontalCenterOffset: root.shakeOffset
      color: root.background
      borderSpec: root.borderSpec
      padding: root.contentMargin

      MouseArea { anchors.fill: parent; onClicked: root.refocus() }

      Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true

        Keys.priority: Keys.BeforeItem
        Keys.onPressed: function(event) {
          if (event.key === Qt.Key_Escape) {
            root.cancelRequest()
            event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            if (root.responseRequired) root.submitResponse()
            event.accepted = true
          }
        }
      }

      // Fingerprint mode shows just the sensor icon, centered and alone \u2014 no
      // padlock, no field, no prompt text.
      OpticalGlyph {
        anchors.centerIn: parent
        width: Math.round(root.fieldHeight * 0.7)
        height: width
        visible: root.fingerprintMode
        text: "\udb80\ude37"
        fontFamily: root.fontFamily
        fontSize: Math.round(root.fieldHeight * 0.7)
        color: root.errorFlash ? Commons.Color.polkit.textError : root.accent
      }

      Row {
        id: cardRow
        visible: !root.fingerprintMode
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset
        spacing: Style.space(14)

        Text {
          text: "\uf023"
          color: root.errorFlash ? Commons.Color.polkit.textError : root.accent
          font.family: root.fontFamily
          font.pixelSize: Style.font.iconLarge
          width: Style.space(26)
          height: root.fieldHeight
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
        }

        Item {
          width: parent.width - Style.space(40)
          height: root.fieldHeight

          TextInput {
            id: passwordInput
            anchors.fill: parent
            verticalAlignment: TextInput.AlignVCenter
            activeFocusOnPress: true
            clip: true
            selectionColor: Util.alpha(root.accent, 0.45)
            selectedTextColor: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.iconLarge
            echoMode: root.responseVisible ? TextInput.Normal : TextInput.Password
            passwordCharacter: "\u2022"
            color: root.errorFlash ? Commons.Color.polkit.textError : root.foreground
            cursorVisible: activeFocus && !root.submitted && !root.errorFlash
            readOnly: root.submitted || root.errorFlash
            enabled: root.dialogVisible
            onAccepted: root.submitResponse()
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Escape) {
                root.cancelRequest()
                event.accepted = true
              }
            }
          }

          Text {
            textFormat: Text.PlainText
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: root.errorFlash ? I18n.t("polkit.wrong") : (root.submitted ? I18n.t("polkit.checking") : I18n.t("polkit.enterPassword"))
            color: root.errorFlash ? Commons.Color.polkit.textError : root.foreground
            opacity: root.errorFlash ? 1 : 0.36
            font.family: root.fontFamily
            font.pixelSize: Style.font.iconLarge
            elide: Text.ElideRight
            visible: passwordInput.text.length === 0
          }

          Rectangle {
            width: Math.max(1, Style.space(2))
            height: Style.space(24)
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            color: root.errorFlash ? Commons.Color.polkit.textError : root.foreground
            visible: passwordInput.visible && passwordInput.activeFocus && passwordInput.text.length === 0 && !root.submitted && !root.errorFlash
          }

          MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            enabled: passwordInput.visible
            onClicked: passwordInput.forceActiveFocus()
          }
        }
      }
    }

    // Action label, requesting command, and (for agent requests) the review.
    // Every Text here is PlainText: the command and verdict are untrusted.
    Rectangle {
      id: infoCard
      readonly property bool hasCommand: !!(root.request && root.request.found)
      readonly property bool expanded: hasCommand || (root.request && !root.request.found) || root.reviewState !== ""
      width: expanded ? root.infoWidth : Math.min(justificationText.implicitWidth + Style.space(24), panel.width - Style.gapsOut * 2)
      height: expanded ? infoColumn.implicitHeight + Style.space(20) : Style.space(28)
      anchors.horizontalCenter: card.horizontalCenter
      anchors.bottom: card.top
      anchors.bottomMargin: Style.space(10)
      radius: root.cornerRadius
      color: root.background
      border.width: root.reviewState === "done" ? Math.max(1, Style.space(2)) : 0
      border.color: root.verdictColor

      Text {
        id: justificationText
        visible: !infoCard.expanded
        textFormat: Text.PlainText
        anchors.fill: parent
        anchors.leftMargin: Style.space(12)
        anchors.rightMargin: Style.space(12)
        text: root.authorizationLabel(root.currentMessage)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideMiddle
      }

      Column {
        id: infoColumn
        visible: infoCard.expanded
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.topMargin: Style.space(10)
        anchors.leftMargin: Style.space(14)
        anchors.rightMargin: Style.space(14)
        spacing: Style.space(6)

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: root.authorizationLabel(root.currentMessage)
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideMiddle
        }

        Text {
          width: parent.width
          visible: infoCard.hasCommand
          textFormat: Text.PlainText
          text: infoCard.hasCommand
            ? strings.t("request.requestedBy").arg((root.request.chain || []).join(" → ")) + (root.request.exact ? "" : "  (" + strings.t("request.likely") + ")")
            : ""
          color: root.foreground
          opacity: 0.6
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideLeft
        }

        Text {
          width: parent.width
          visible: !!(root.request && !root.request.found)
          textFormat: Text.PlainText
          text: strings.t("request.unknown")
          color: root.foreground
          opacity: 0.6
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
        }

        Rectangle {
          width: parent.width
          visible: infoCard.hasCommand
          height: commandText.implicitHeight + Style.space(12)
          radius: Math.max(0, root.cornerRadius - 2)
          color: Util.alpha(root.foreground, 0.07)

          Text {
            id: commandText
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: Style.space(8)
            anchors.rightMargin: Style.space(8)
            textFormat: Text.PlainText
            text: infoCard.hasCommand ? "$ " + root.request.command : ""
            color: root.foreground
            font.family: "monospace"
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WrapAnywhere
            maximumLineCount: 6
            elide: Text.ElideRight
          }
        }

        Text {
          width: parent.width
          visible: root.reviewState !== ""
          textFormat: Text.PlainText
          text: root.reviewState === "running"
            ? strings.t("review.running").arg(root.reviewSeconds)
            : (root.review
                ? strings.t("review." + root.review.verdict) + " — " + (root.review.summary || "")
                  + (root.review.reviewer ? "  (" + strings.t("review.by").arg(root.review.reviewer) + ")" : "")
                  + (root.review.cachedAt ? "  (" + strings.t("review.cached").arg(Math.max(1, Math.round((Date.now() - root.review.cachedAt) / 60000))) + ")" : "")
                : "")
          color: root.verdictColor
          opacity: root.reviewState === "running" ? 0.7 : 1
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.bold: root.reviewState === "done"
          wrapMode: Text.Wrap
        }

        Text {
          width: parent.width
          visible: root.reviewState === "done" && !!(root.review && root.review.details)
          textFormat: Text.PlainText
          text: root.review ? (root.review.details || "") : ""
          color: root.foreground
          opacity: 0.8
          font.family: root.fontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.Wrap
          maximumLineCount: 10
          elide: Text.ElideRight
        }
      }
    }
  }
}
