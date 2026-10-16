import Foundation
import Observation

/// Each project chat's group of pixies, for the tree under its row (B46), and the one work
/// page open, which follows the live events.
@MainActor @Observable
public final class ChatPixiesStore {
    private var groups: [String: [ChatPixieEntry]] = [:]
    /// The work page open, if any.
    public private(set) var work: AgentWorkStore?

    let api: any NestAPI
    @ObservationIgnored private let live = LiveEventLog()

    public init(api: any NestAPI) {
        self.api = api
    }

    /// Reads every chat's group; events that arrive meanwhile apply again on top. A failed
    /// read (such as an older daemon's) keeps what was there and never fails the sync.
    public func load() async {
        _ = try? await live.read {
            try await self.api.pixieGroups()
        } store: { groups in
            self.groups = groups.filter { !$0.value.isEmpty }
        } replay: {
            apply($0)
        }
    }

    /// The chat's pixies and teams, first called first; empty when it called none.
    public func group(session id: String) -> [ChatPixieEntry] {
        groups[id] ?? []
    }

    /// The pixie, or the team with its members, leaves the chat's group; the next call
    /// starts fresh.
    public func sendAway(_ entry: ChatPixieEntry, session id: String) async throws {
        store(try await api.sendAway(id, entry.sendAway), for: id)
    }

    public func apply(_ event: Event) {
        live.record(event)
        work?.receive(event)
        switch event.body {
        case .pixieGroup(let group):
            guard let id = event.sessionID else { return }
            store(group, for: id)
        case .sessionDeleted(let id):
            groups[id] = nil
        default:
            break
        }
    }

    /// Opens a work page and reads it.
    public func open(_ target: WorkTarget) async {
        let page = AgentWorkStore(target: target, api: api)
        work = page
        await page.load()
    }

    public func closeWork() {
        work = nil
    }

    private func store(_ group: [ChatPixieEntry], for id: String) {
        groups[id] = group.isEmpty ? nil : group
    }
}
