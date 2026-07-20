import AppKit
import Foundation

// =============================================================================
// main.swift  ·  menu-bar app lifecycle + consent/pause control (PRD §3, §6)
// =============================================================================
// The whole agent, wired together: a menu-bar presence (NSStatusItem) that
// gives the patient an always-visible on/off control (§3: see, pause, stop),
// a Telemetry observer, a Batcher, and one timer that drains a bucket every
// BUCKET_SECONDS and flushes. No abstraction beyond these pieces (§6).
//
// Collection is OFF until the patient explicitly starts it -- consent is a
// deliberate action, not a default (§3: explicit, informed consent before any
// collection begins).
// =============================================================================

// How often we bucket + send. 60s = per-minute counts (§5.2 "keystrokes/minute").
let BUCKET_SECONDS: Double = 60

// Backend base URL. Localhost only -- nothing leaves the machine (§4). Override
// with NORTHLIGHT_BACKEND_URL if the backend runs elsewhere.
let BACKEND_URL = URL(string: ProcessInfo.processInfo.environment["NORTHLIGHT_BACKEND_URL"]
                      ?? "http://127.0.0.1:8000")!

final class AgentController: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let telemetry = Telemetry()
    private var batcher: Batcher!
    private var timer: Timer?
    private var collecting = false          // OFF until the patient consents

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Menu-bar-only app: no Dock icon, no main window. The status item IS
        // the UI, which keeps the agent's presence obvious and unobtrusive.
        NSApp.setActivationPolicy(.accessory)

        let pseudonym = Pseudonym.current()      // hashed local id; raw id stays here
        batcher = Batcher(backendURL: BACKEND_URL, pseudonym: pseudonym)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "◎ NL"        // paused glyph until started
        rebuildMenu()

        // Observers are installed now, but nothing is sent until the patient
        // presses Start -- see toggleCollection().
        telemetry.start()
    }

    // --- the menu: transparency + control (§3) -------------------------------
    private func rebuildMenu() {
        let menu = NSMenu()

        let status = NSMenuItem(
            title: collecting ? "● Collecting activity signal" : "◎ Paused — not collecting",
            action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(.separator())

        // The plain-language "what is / isn't collected" statement (§11.3). Put
        // it right in the menu so the patient can read it any time.
        let whatItem = NSMenuItem(
            title: "Collected: counts, durations, app names — never content",
            action: #selector(showPrivacyInfo), keyEquivalent: "")
        whatItem.target = self
        menu.addItem(whatItem)
        menu.addItem(.separator())

        let toggle = NSMenuItem(
            title: collecting ? "Pause collection" : "Start collection (consent)",
            action: #selector(toggleCollection), keyEquivalent: "")
        toggle.target = self
        menu.addItem(toggle)

        let quit = NSMenuItem(title: "Quit NorthLight Agent",
                              action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)

        statusItem.menu = menu
    }

    // --- start/pause: the consent gate ---------------------------------------
    @objc private func toggleCollection() {
        collecting.toggle()
        if collecting {
            // Begin the per-bucket drain+flush loop.
            let t = Timer(timeInterval: BUCKET_SECONDS, repeats: true) { [weak self] _ in
                self?.tick()
            }
            RunLoop.main.add(t, forMode: .common)
            timer = t
            statusItem.button?.title = "● NL"
        } else {
            timer?.invalidate(); timer = nil
            batcher.flush()                  // send whatever is buffered, then stop
            statusItem.button?.title = "◎ NL"
        }
        rebuildMenu()
    }

    // --- one bucket: drain counters, fold into events, POST ------------------
    private func tick() {
        let snap = telemetry.drain()
        let idle = telemetry.idleSeconds()
        batcher.ingest(snap, idleSeconds: idle, bucketSeconds: BUCKET_SECONDS)
        batcher.flush()
    }

    @objc private func showPrivacyInfo() {
        // The patient-facing explanation, verbatim from PRD §11.3.
        let alert = NSAlert()
        alert.messageText = "What NorthLight collects"
        alert.informativeText = """
        Collected: how much you use your computer, when you're active vs away, \
        which applications you switch between, and how often — as counts and \
        durations.

        NOT collected: the words you type, the passwords you enter, the \
        websites you visit, the contents of your screen, or images of anything \
        you do.

        We measure the rhythm of activity, not its content.
        """
        alert.runModal()
    }

    @objc private func quit() {
        if collecting { batcher.flush() }
        NSApp.terminate(nil)
    }
}

// --- app entry point ---------------------------------------------------------
let app = NSApplication.shared
let controller = AgentController()
app.delegate = controller
app.run()
