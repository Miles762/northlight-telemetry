import Foundation
import CryptoKit

// =============================================================================
// Pseudonym.swift  ·  the hashed local install id (PRD §2, §11.4)
// =============================================================================
// The database is keyed on a PSEUDONYM, never a name or email. That pseudonym
// is produced HERE, on the device, and only the hash is ever sent to the
// backend. The raw identifier that seeds the hash never leaves this machine.
//
// How the raw identifier is chosen: on first run we generate a random UUID and
// persist it to a file inside the agent's Application Support directory. That
// UUID is the "local install id." It is:
//   - not the hardware serial, not the MAC address, not the user's name --
//     nothing that ties back to a real identity or survives a reinstall;
//   - stable across runs so the same install maps to the same pseudonym (so the
//     backend can accumulate a per-person baseline over days);
//   - hashed with SHA-256 before it is used as the pseudonym, so even the value
//     we send is a one-way digest of a value that was already random.
// =============================================================================

enum Pseudonym {

    /// Returns the SHA-256 hash (hex) of this install's local id, creating and
    /// persisting the raw id on first run. Only the returned hash is sent.
    static func current() -> String {
        let rawInstallId = loadOrCreateRawInstallId()

        // SHA-256 the raw id. The digest is what becomes the `pseudonym` column
        // in Postgres. Hashing a random UUID is belt-and-suspenders: the seed is
        // already non-identifying, and the hash makes that irreversible.
        let digest = SHA256.hash(data: Data(rawInstallId.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    // -- raw install id: generated once, stored locally, never transmitted -----

    private static func rawIdFileURL() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory,
                                            in: .userDomainMask)[0]
            .appendingPathComponent("NorthLightAgent", isDirectory: true)
        try? FileManager.default.createDirectory(at: base,
                                                 withIntermediateDirectories: true)
        // This file holds the ONLY copy of the raw id. It stays on disk here and
        // is read to derive the hash; it is never included in any network call.
        return base.appendingPathComponent("install-id")
    }

    private static func loadOrCreateRawInstallId() -> String {
        let url = rawIdFileURL()
        if let existing = try? String(contentsOf: url, encoding: .utf8),
           !existing.isEmpty {
            return existing.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        // First run: a fresh random UUID. Random, so it identifies the install,
        // not the human -- there is no way to reverse it to a person.
        let fresh = UUID().uuidString
        try? fresh.write(to: url, atomically: true, encoding: .utf8)
        return fresh
    }
}
