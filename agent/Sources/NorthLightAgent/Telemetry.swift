import AppKit
import IOKit
import Foundation

// =============================================================================
// Telemetry.swift  ·  the observers (PRD §5, §6)
// =============================================================================
// This is the only file that touches OS activity. Every system API below is
// annotated with WHAT IT OBSERVES and WHAT IT DELIBERATELY DOES NOT READ, per
// the PRD's explainability requirement (§6). The content-exclusion boundary
// (§1, §6) is visible in the input handlers: they read a count and DISCARD the
// event object in the same closure, so no key, character, or coordinate is ever
// retained.
//
// The class holds mutable counters that the Batcher drains once per bucket. It
// does no networking itself -- one responsibility: observe and count.
// =============================================================================

final class Telemetry {

    // --- counters drained per bucket (all just integers/durations) -----------
    private(set) var keyboardCount = 0        // number of key events this bucket
    private(set) var mouseCount = 0           // clicks + scrolls this bucket
    private(set) var appSwitchCount = 0       // foreground-app changes this bucket

    // Foreground-app focus accounting: which app has focus and since when, so we
    // can emit a per-app focus DURATION on each switch. App NAME only.
    private(set) var currentAppName: String?
    private var currentAppSince = Date()

    // Completed focus spans since the last drain: (appName, seconds). Name only.
    private(set) var focusSpans: [(app: String, seconds: Double)] = []

    // Discrete session transitions observed since last drain (lock/unlock/etc).
    private(set) var transitions: [(type: String, at: Date)] = []

    private var keyboardMonitor: Any?
    private var mouseMonitor: Any?

    // -------------------------------------------------------------------------
    // start(): install all observers.
    // -------------------------------------------------------------------------
    func start() {
        installInputMonitors()
        installAppFocusObserver()
        installSystemSignalObservers()
        // Seed the initial foreground app so the first switch has a prior span.
        currentAppName = NSWorkspace.shared.frontmostApplication?.localizedName
        currentAppSince = Date()
    }

    // -------------------------------------------------------------------------
    // 1. KEYBOARD + MOUSE — global event monitors (PRD §5.2, §5.3)
    // -------------------------------------------------------------------------
    // API: NSEvent.addGlobalMonitorForEvents(matching:handler:)
    //
    // OBSERVES: THAT an input event occurred, and its coarse type (key vs mouse).
    //   A global monitor is passive and notification-only -- it cannot alter or
    //   swallow the event; it just tells us one happened.
    //
    // DELIBERATELY DOES NOT READ: which key/character (event.keyCode,
    //   event.characters), modifier state, mouse coordinates, or click targets.
    //   The handler NEVER touches those properties. It increments a counter and
    //   lets the NSEvent go out of scope untouched -- the content-exclusion
    //   boundary is these two closures. This is why it is a counter, not a log:
    //   a per-minute count is the entire clinical signal (§5.2), and reading the
    //   keys would make this a keylogger for zero added value.
    private func installInputMonitors() {
        keyboardMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.keyDown]
        ) { [weak self] _ in            // `_`: the NSEvent is intentionally ignored
            self?.keyboardCount += 1     // count only; nothing about the key is read
        }

        mouseMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.leftMouseDown, .rightMouseDown, .scrollWheel]
        ) { [weak self] _ in            // `_`: coordinates/target intentionally ignored
            self?.mouseCount += 1        // count only; no location, no target
        }
    }

    // -------------------------------------------------------------------------
    // 2. FOREGROUND APPLICATION — NSWorkspace focus notifications (PRD §5.4)
    // -------------------------------------------------------------------------
    // API: NSWorkspace.didActivateApplicationNotification
    //
    // OBSERVES: that focus moved to a different application, and that app's
    //   localizedName (e.g. "Safari", "VS Code"), plus how long the previous app
    //   held focus (computed from timestamps). Switch COUNT is the attention-
    //   fragmentation proxy (§5.4).
    //
    // DELIBERATELY DOES NOT READ: window titles, document names, browser URLs,
    //   or any window/screen contents. We take ONLY `localizedName`. The PRD
    //   marks window titles opt-in and sensitive (§5.4); the default path here
    //   never reads them, so `window_title` leaves this agent nil.
    private func installAppFocusObserver() {
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil, queue: .main
        ) { [weak self] note in
            guard let self else { return }
            let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            // App NAME only. We never reach for a window title or any content.
            let newName = app?.localizedName ?? "Unknown"

            // Close the previous app's focus span (name + duration) and open the
            // new one. Duration is a plain time delta -- no content involved.
            let now = Date()
            if let prev = self.currentAppName {
                let seconds = now.timeIntervalSince(self.currentAppSince)
                if seconds > 0 { self.focusSpans.append((app: prev, seconds: seconds)) }
            }
            self.currentAppName = newName
            self.currentAppSince = now
            self.appSwitchCount += 1
        }
    }

    // -------------------------------------------------------------------------
    // 3. SYSTEM SIGNALS — lock/unlock, sleep/wake (PRD §5.1, §5.5)
    // -------------------------------------------------------------------------
    // APIs:
    //   - NSWorkspace notifications: willSleep / didWake  (sleep/wake)
    //   - DistributedNotificationCenter: com.apple.screenIsLocked /
    //     com.apple.screenIsUnlocked  (screen lock/unlock)
    //
    // OBSERVES: THAT a session boundary happened and WHEN (a timestamp). These
    //   mark the day's rhythm -- present, away, asleep -- and bound sessions.
    //
    // DELIBERATELY DOES NOT READ: anything about the lock screen, credentials,
    //   what woke the machine, or any content. Each handler records only a
    //   transition type string and the time.
    //
    // Battery/network/display signals are [FUTURE] (§5.5) and intentionally not
    // observed here -- they don't change the core metrics.
    private func installSystemSignalObservers() {
        let ws = NSWorkspace.shared.notificationCenter
        ws.addObserver(forName: NSWorkspace.willSleepNotification,
                       object: nil, queue: .main) { [weak self] _ in
            self?.transitions.append((type: "sleep", at: Date()))   // time only
        }
        ws.addObserver(forName: NSWorkspace.didWakeNotification,
                       object: nil, queue: .main) { [weak self] _ in
            self?.transitions.append((type: "wake", at: Date()))    // time only
        }

        // Lock/unlock arrive as system-wide "distributed" notifications, not on
        // the workspace center. We observe the two names and record time only.
        let dc = DistributedNotificationCenter.default()
        dc.addObserver(forName: .init("com.apple.screenIsLocked"),
                       object: nil, queue: .main) { [weak self] _ in
            self?.transitions.append((type: "lock", at: Date()))
        }
        dc.addObserver(forName: .init("com.apple.screenIsUnlocked"),
                       object: nil, queue: .main) { [weak self] _ in
            self?.transitions.append((type: "unlock", at: Date()))
        }
    }

    // -------------------------------------------------------------------------
    // 4. IDLE TIME — IOKit HID system idle query (PRD §5.1)
    // -------------------------------------------------------------------------
    // API: IOHIDSystem's "HIDIdleTime" property, read via IORegistry.
    //
    // OBSERVES: seconds since the last HID (keyboard/mouse) input, system-wide.
    //   This is a single number -- how long the machine has been idle -- used to
    //   split active vs idle time (§5.1) without watching individual events.
    //
    // DELIBERATELY DOES NOT READ: which input ended the idle period or anything
    //   about it. It is one integer: elapsed idle seconds. No content exists to
    //   leak in a duration.
    func idleSeconds() -> Double {
        let service = IOServiceGetMatchingService(
            kIOMainPortDefault, IOServiceMatching("IOHIDSystem"))
        defer { IOObjectRelease(service) }
        guard service != 0 else { return 0 }

        // Returns the property value directly as an Unmanaged CFTypeRef (or nil).
        guard let prop = IORegistryEntryCreateCFProperty(
            service, "HIDIdleTime" as CFString, kCFAllocatorDefault, 0) else {
            return 0
        }
        let value = prop.takeRetainedValue()
        guard let number = value as? NSNumber else { return 0 }
        // HIDIdleTime is in nanoseconds; convert to seconds.
        return number.doubleValue / 1_000_000_000.0
    }

    // -------------------------------------------------------------------------
    // drain(): hand the current counters/spans to the Batcher and reset them.
    // Returns a snapshot; the Batcher turns it into events. Called once/bucket.
    // -------------------------------------------------------------------------
    struct Snapshot {
        let keyboardCount: Int
        let mouseCount: Int
        let appSwitchCount: Int
        let focusSpans: [(app: String, seconds: Double)]
        let transitions: [(type: String, at: Date)]
        // The open app's running span, so app-usage totals include time-in-focus
        // that hasn't hit a switch yet. Name + duration only.
        let openApp: String?
        let openAppSeconds: Double
    }

    func drain() -> Snapshot {
        let openSeconds = Date().timeIntervalSince(currentAppSince)
        let snap = Snapshot(
            keyboardCount: keyboardCount,
            mouseCount: mouseCount,
            appSwitchCount: appSwitchCount,
            focusSpans: focusSpans,
            transitions: transitions,
            openApp: currentAppName,
            openAppSeconds: openSeconds
        )
        // Reset counters; keep currentApp/Since so the open span continues.
        keyboardCount = 0
        mouseCount = 0
        appSwitchCount = 0
        focusSpans = []
        transitions = []
        currentAppSince = Date()
        return snap
    }
}
