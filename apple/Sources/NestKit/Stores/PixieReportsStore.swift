import Foundation
import Observation

/// What pixies reported, newest first (B42): the cards in their chats read them here, the
/// inbox lists the unread warnings and actions, and unread actions count in the Dock badge
/// and the Pixies tab.
@MainActor @Observable
public final class PixieReportsStore {
    public private(set) var reports: [PixieReport] = []

    let api: any NestAPI
    let now: @Sendable () -> Date

    public init(api: any NestAPI, now: @escaping @Sendable () -> Date = { Date() }) {
        self.api = api
        self.now = now
    }

    /// The latest reports and every unread one, so an old unread one is not missed.
    public func load() async throws {
        let recent = try await api.pixieReports(unread: false)
        let unread = try await api.pixieReports(unread: true)
        var byID: [String: PixieReport] = [:]
        for report in recent + unread {
            byID[report.id] = report
        }
        reports = Self.sorted(Array(byID.values))
    }

    public func report(_ id: String) -> PixieReport? {
        reports.first { $0.id == id }
    }

    /// Unread warnings and actions, newest first.
    public var inbox: [PixieReport] {
        reports.filter { $0.isUnread && $0.severity >= .warn }
    }

    /// Unread reports that need action, of one pixie or of all.
    public func unreadActions(of pixie: String? = nil) -> Int {
        reports.count {
            $0.isUnread && $0.severity == .action && (pixie ?? $0.pixieID) == $0.pixieID
        }
    }

    /// The pixie's unread reports of any severity.
    public func unread(of pixie: String) -> Int {
        reports.count { $0.isUnread && $0.pixieID == pixie }
    }

    public func apply(_ event: Event) {
        switch event.body {
        case .pixieReport(let report):
            reports = Self.sorted(reports.filter { $0.id != report.id } + [report])
        case .pixieReportRead(let ids):
            setRead(Set(ids), true)
        case .pixieDeleted(let pixie):
            reports.removeAll { $0.pixieID == pixie }
        default:
            break
        }
    }

    /// Dismiss: shows it read at once; a refusal shows it unread again.
    public func markRead(_ id: String) async throws {
        guard report(id)?.isUnread == true else { return }
        try await marking([id]) { try await self.api.markReportRead(id) }
    }

    /// Opening a pixie reads all its reports.
    public func markPixieRead(_ pixie: String) async throws {
        let ids = Set(reports.filter { $0.isUnread && $0.pixieID == pixie }.map(\.id))
        guard !ids.isEmpty else { return }
        try await marking(ids) { try await self.api.markPixieReportsRead(pixie) }
    }

    private func marking(_ ids: Set<String>, _ call: () async throws -> Void) async throws {
        setRead(ids, true)
        do {
            try await call()
        } catch {
            setRead(ids, false)
            throw error
        }
    }

    /// Marks unread ones read now, or read ones unread again.
    private func setRead(_ ids: Set<String>, _ read: Bool) {
        let time = now()
        reports = reports.map { report in
            var report = report
            if ids.contains(report.id) && report.isUnread == read {
                report.readAt = read ? time : nil
            }
            return report
        }
    }

    private static func sorted(_ list: [PixieReport]) -> [PixieReport] {
        list.sorted { ($0.createdAt, $0.id) > ($1.createdAt, $1.id) }
    }
}
