import Foundation

/// The live events that arrive while REST reads are on their way. A read answers with
/// what the daemon had before those events, so once its answer is stored they apply
/// again on top of it rather than being undone by it (PL-06). A class, so recording can
/// happen while a read waits.
@MainActor
final class LiveEventLog {
    private var lastToken = 0
    private var open: [Int: [Event]] = [:]

    /// Notes an event for every read in flight.
    func record(_ event: Event) {
        for token in open.keys {
            open[token]?.append(event)
        }
    }

    /// Runs a read, stores its answer and applies again, oldest first, the events that
    /// arrived meanwhile.
    func read<T>(
        _ fetch: () async throws -> T, store: (T) -> Void, replay: (Event) -> Void
    ) async throws -> T {
        lastToken += 1
        let token = lastToken
        open[token] = []
        defer { open[token] = nil }
        let value = try await fetch()
        store(value)
        open[token]?.forEach(replay)
        return value
    }
}
