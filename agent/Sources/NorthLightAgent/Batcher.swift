import Foundation

// =============================================================================
// Batcher.swift  ·  bucketing buffer + POST to the backend (PRD §5, §8.1)
// =============================================================================
// Turns per-bucket Telemetry snapshots into the event shape the FastAPI backend
// accepts, buffers them, and POSTs to /events. It carries the privacy contract
// into the wire format: every event is a count, a duration, or an app name --
// there is no field here for content or window titles.
//
// Matches the backend contract (backend/app/models.py):
//   { "batch_id": UUID, "pseudonym": str, "events": [ {event_type, ts,
//     numeric_value?, app_name?} ] }
// =============================================================================

private let MAX_EVENTS_PER_BATCH = 500
private let MAX_BUFFERED_EVENTS = 5_000

/// One event exactly as the backend's EventIn expects. Encodable to JSON.
private struct AgentEvent: Encodable {
    let event_type: String
    let ts: String                 // ISO-8601
    let numeric_value: Double?
    let app_name: String?
}

private struct Payload: Encodable {
    let batch_id: String           // UUID; reused on retry so a resend is a no-op
    let pseudonym: String
    let events: [AgentEvent]
}

final class Batcher {
    private let backendURL: URL
    private let pseudonym: String
    private var buffer: [AgentEvent] = []

    // A batch_id minted per flush attempt. Held until the POST succeeds so a
    // retry of the SAME batch reuses it (backend dedups on batch_id, §4 NFR).
    private var pendingBatchId: String?
    private var pendingEvents: [AgentEvent]?
    private var flushInFlight = false

    private let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    init(backendURL: URL, pseudonym: String) {
        self.backendURL = backendURL
        self.pseudonym = pseudonym
    }

    // -------------------------------------------------------------------------
    // ingest(): fold one bucket's snapshot into buffered events.
    //   - keyboard/mouse -> a single count event each (COUNT, not keys)
    //   - each app focus span -> an app_focus event (name + duration seconds)
    //   - the still-open app's running span -> an app_focus event too, so
    //     app-usage totals reflect current focus
    //   - active/idle split from the idle probe -> active/idle events (seconds)
    //   - lock/unlock/sleep/wake transitions -> one event each (time only)
    //   - power/network/display states -> coarse numeric states only
    // -------------------------------------------------------------------------
    func ingest(_ snap: Telemetry.Snapshot, idleSeconds: Double, bucketSeconds: Double) {
        let nowDate = Date()
        let now = iso.string(from: nowDate)
        let bucketStartDate = nowDate.addingTimeInterval(-bucketSeconds)
        let bucketStart = iso.string(from: bucketStartDate)

        if snap.keyboardCount > 0 {
            append(AgentEvent(event_type: "keyboard", ts: now,
                              numeric_value: Double(snap.keyboardCount),
                              app_name: nil))
        }
        if snap.mouseCount > 0 {
            append(AgentEvent(event_type: "mouse", ts: now,
                              numeric_value: Double(snap.mouseCount),
                              app_name: nil))
        }

        // Completed focus spans (name + seconds). App NAME only.
        for span in snap.focusSpans where span.seconds > 0 {
            append(AgentEvent(event_type: "app_focus", ts: now,
                              numeric_value: span.seconds,
                              app_name: span.app))
        }
        // The currently-focused app's running span this bucket. This is re-emitted
        // every bucket so app-usage DURATION totals stay accurate even while an app
        // stays focused across buckets. It intentionally does NOT represent a switch.
        if let open = snap.openApp, snap.openAppSeconds > 0 {
            append(AgentEvent(event_type: "app_focus", ts: now,
                              numeric_value: snap.openAppSeconds,
                              app_name: open))
        }

        // App-switch COUNT as its own signal. The agent already counted only real
        // foreground-app changes (Telemetry.appSwitchCount); we send that number
        // directly instead of letting the backend infer switches from the number of
        // app_focus rows -- app_focus rows re-emit open spans each bucket and would
        // otherwise inflate the switch count (and the attention-fragmentation signal).
        if snap.appSwitchCount > 0 {
            append(AgentEvent(event_type: "app_switch", ts: now,
                              numeric_value: Double(snap.appSwitchCount),
                              app_name: nil))
        }

        // Active vs idle seconds for this bucket, derived from the idle probe.
        // If idle >= the whole bucket, the bucket was idle; otherwise the
        // non-idle remainder was active. Durations only -- no content.
        let idleThisBucket = min(idleSeconds, bucketSeconds)
        let activeThisBucket = max(0, bucketSeconds - idleThisBucket)
        if activeThisBucket > 0 {
            append(AgentEvent(event_type: "active", ts: bucketStart,
                              numeric_value: activeThisBucket, app_name: nil))
        }
        if idleThisBucket > 0 {
            let idleStart = iso.string(from: nowDate.addingTimeInterval(-idleThisBucket))
            append(AgentEvent(event_type: "idle", ts: idleStart,
                              numeric_value: idleThisBucket, app_name: nil))
        }

        // Session transitions -- one event each, timestamped when observed.
        for t in snap.transitions {
            append(AgentEvent(event_type: t.type,
                              ts: iso.string(from: t.at),
                              numeric_value: nil, app_name: nil))
        }

        // System-level signals: AC power present (1/0), battery percent, network
        // connected (1/0), display count. No SSID/IP/display identity/content.
        for e in snap.systemEvents {
            append(AgentEvent(event_type: e.type,
                              ts: iso.string(from: e.at),
                              numeric_value: e.numericValue,
                              app_name: nil))
        }
    }

    // -------------------------------------------------------------------------
    // flush(): POST the buffer to /events. On success, clear it; on failure keep
    // it (and the batch_id) so the next flush retries the SAME batch -> the
    // backend recognizes the batch_id and does not double-count (§4 NFR).
    // -------------------------------------------------------------------------
    func flush() {
        guard !flushInFlight else { return }
        guard pendingEvents != nil || !buffer.isEmpty else { return }

        // Reuse the pending id if a prior flush failed; else mint a new one.
        let batchId = pendingBatchId ?? UUID().uuidString
        pendingBatchId = batchId
        let sending = pendingEvents ?? Array(buffer.prefix(MAX_EVENTS_PER_BATCH))
        pendingEvents = sending

        let payload = Payload(batch_id: batchId, pseudonym: pseudonym, events: sending)
        guard let body = try? JSONEncoder().encode(payload) else { return }

        var req = URLRequest(url: backendURL.appendingPathComponent("events"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = body

        flushInFlight = true
        URLSession.shared.dataTask(with: req) { [weak self] _, resp, err in
            guard let self else { return }
            DispatchQueue.main.async {
                self.flushInFlight = false
                let ok = (resp as? HTTPURLResponse).map { (200..<300).contains($0.statusCode) } ?? false
                if err == nil && ok {
                    // Remove exactly what we sent; new events during the POST stay.
                    self.buffer.removeFirst(min(sending.count, self.buffer.count))
                    self.pendingBatchId = nil          // this batch is done
                    self.pendingEvents = nil
                    NSLog("NorthLight: flushed \(sending.count) events")
                } else {
                    // Keep buffer + batch_id; next flush retries the same batch.
                    NSLog("NorthLight: flush failed, will retry (\(err?.localizedDescription ?? "http error"))")
                }
            }
        }.resume()
    }

    private func append(_ event: AgentEvent) {
        buffer.append(event)
        let overflow = buffer.count - MAX_BUFFERED_EVENTS
        if overflow > 0 {
            let protected = pendingEvents?.count ?? 0
            let removable = max(0, buffer.count - protected)
            let removeCount = min(overflow, removable)
            if removeCount > 0 {
                buffer.removeSubrange(protected..<(protected + removeCount))
                NSLog("NorthLight: dropped \(removeCount) oldest buffered event(s) after reaching local buffer cap")
            }
        }
    }
}
