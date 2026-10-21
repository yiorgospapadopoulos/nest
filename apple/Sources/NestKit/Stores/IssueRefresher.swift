import Foundation

/// Keeps the visible start screen's open issues current (B101): its project's issues are
/// read again every interval while it shows, and when the app or its window comes back.
/// Reads go through `IssuesStore.load`, which keeps the list on screen and the All or Mine
/// choice, and keeps the last list when a read fails. The daemon caches issues for a
/// minute, so these reads never ask it to refresh.
@MainActor
public final class IssueRefresher {
    /// The project whose start screen shows; nil when none does.
    public private(set) var repo: String?
    private let issues: IssuesStore
    private let interval: Duration
    private let sleep: @Sendable (Duration) async throws -> Void
    private var timer: Task<Void, Never>?

    public init(
        issues: IssuesStore, interval: Duration = .seconds(60),
        sleep: @escaping @Sendable (Duration) async throws -> Void = IssueRefresher.sleep
    ) {
        self.issues = issues
        self.interval = interval
        self.sleep = sleep
    }

    /// The timer's wait between reads.
    public nonisolated static func sleep(_ interval: Duration) async throws {
        try await Task.sleep(for: interval)
    }

    /// The project's start screen appeared: read its issues on each interval.
    public func start(_ repo: String) {
        stop()
        self.repo = repo
        timer = Task { [issues, interval, sleep] in
            while !Task.isCancelled {
                try? await sleep(interval)
                guard !Task.isCancelled else { return }
                await issues.load(repo)
            }
        }
    }

    /// The start screen went away.
    public func stop() {
        timer?.cancel()
        timer = nil
        repo = nil
    }

    /// The app became active or the window key again: read now while a start screen shows.
    public func wake() async {
        if let repo {
            await issues.load(repo)
        }
    }
}
