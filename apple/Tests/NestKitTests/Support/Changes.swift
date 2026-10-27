import Foundation
import Synchronization
import Testing

/// Lets a test wait for a fake's state instead of polling it: the fake notes each change,
/// and every wait whose condition then holds ends. A wait that never ends fails the test
/// after `limit` rather than hanging the run.
final class Changes: Sendable {
    private struct Waiter {
        let id: UUID
        let holds: @Sendable () -> Bool
        let continuation: CheckedContinuation<Void, Never>
        let watchdog: Task<Void, Never>
    }

    private let waiters = Mutex<[Waiter]>([])
    static let limit = Duration.seconds(10)

    /// Ends once `holds` is true, checked now and after each `note()`.
    func until(
        fileID: String = #fileID, filePath: String = #filePath, line: Int = #line,
        column: Int = #column, _ holds: @escaping @Sendable () -> Bool
    ) async {
        let id = UUID()
        let sourceLocation = SourceLocation(
            fileID: fileID, filePath: filePath, line: line, column: column)
        await withCheckedContinuation { continuation in
            waiters.withLock { waiters in
                if holds() {
                    continuation.resume()
                    return
                }
                let watchdog = Task { [weak self] in
                    try? await Task.sleep(for: Self.limit)
                    guard !Task.isCancelled, let self, self.drop(id) else { return }
                    Issue.record("The awaited change never came", sourceLocation: sourceLocation)
                }
                waiters.append(
                    Waiter(id: id, holds: holds, continuation: continuation, watchdog: watchdog))
            }
        }
    }

    /// The fake's state changed: ends the waits that now hold. Call it with no lock held.
    func note() {
        waiters.withLock { waiters in
            waiters.removeAll { waiter in
                guard waiter.holds() else { return false }
                waiter.watchdog.cancel()
                waiter.continuation.resume()
                return true
            }
        }
    }

    /// Ends a wait that timed out; false when it already ended.
    private func drop(_ id: UUID) -> Bool {
        let waiter = waiters.withLock { waiters -> Waiter? in
            guard let index = waiters.firstIndex(where: { $0.id == id }) else { return nil }
            return waiters.remove(at: index)
        }
        waiter?.continuation.resume()
        return waiter != nil
    }
}
