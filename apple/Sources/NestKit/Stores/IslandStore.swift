import Foundation
import Observation

/// The island around the notch (B114): its settings, which chats were seen on this Mac,
/// the habit runs, and what it shows now, from the app's stores.
@MainActor @Observable
public final class IslandStore {
    enum Key {
        static let shown = "island.shown"
        static let order = "island.order"
        static let seen = "island.seen"
        static let installedAt = "island.installedAt"
    }

    /// Show the island (on by default).
    public var shown: Bool {
        didSet { store.set(shown ? "on" : "off", forKey: Key.shown) }
    }
    public var order: IslandOrder {
        didSet { store.set(order.rawValue, forKey: Key.order) }
    }
    /// When each chat was last opened or its pixie clicked, by session id.
    public private(set) var seen: [String: Date]
    /// When the island was first shown on this Mac; older finishes never show (C3).
    public let installedAt: Date
    /// When this store was made, so Nightshade starts awake.
    private let startedAt: Date

    /// The latest run of each habit, by habit id.
    private var runs: [String: HabitRun] = [:]
    /// Pixie chats' states from live events, by session id, while the sessions store has
    /// not read them (it lists no pixie chats).
    private var pixieChats: [String: (state: SessionState, at: Date)] = [:]
    /// Chats whose tracked agents were asked for since the last connect.
    @ObservationIgnored private var activityRequested: Set<String> = []
    @ObservationIgnored private let live = LiveEventLog()

    let api: any NestAPI
    let store: any KeyValueStore
    let sessions: SessionsStore
    let approvals: ApprovalsStore
    let activity: ActivityStore
    let chatPixies: ChatPixiesStore
    let pixies: PixiesStore
    let now: @Sendable () -> Date

    public init(
        api: any NestAPI, store: any KeyValueStore, sessions: SessionsStore,
        approvals: ApprovalsStore, activity: ActivityStore, chatPixies: ChatPixiesStore,
        pixies: PixiesStore, now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.api = api
        self.store = store
        self.sessions = sessions
        self.approvals = approvals
        self.activity = activity
        self.chatPixies = chatPixies
        self.pixies = pixies
        self.now = now
        shown = store.string(forKey: Key.shown) != "off"
        order = store.string(forKey: Key.order).flatMap(IslandOrder.init) ?? .newestFirst
        seen = Self.readSeen(store.string(forKey: Key.seen))
        startedAt = now()
        if let stored = store.string(forKey: Key.installedAt).flatMap(Double.init) {
            installedAt = Date(timeIntervalSince1970: stored)
        } else {
            installedAt = now()
            store.set(String(installedAt.timeIntervalSince1970), forKey: Key.installedAt)
        }
    }

    /// What the island shows now; `fullScreen` while a full-screen app is in front, `pill`
    /// on a screen without a notch.
    public func state(fullScreen: Bool = false, pill: Bool = false) -> IslandState {
        IslandState.make(snapshot(fullScreen: fullScreen, pill: pill))
    }

    /// The chat was seen: its done pixies leave and the ones that need the user turn calm.
    /// The Mac app calls this when the chat is focused (user 2026-11-02), when a habit run
    /// opens and on a click on the island.
    public func markSeen(chat id: String) {
        seen[id] = now()
        saveSeen()
    }

    /// What a click does, marking the chat it opens seen.
    @discardableResult
    public func click(_ target: IslandTarget) -> IslandAction {
        let action = IslandAction.of(target)
        if let chat = action.seenChat {
            markSeen(chat: chat)
        }
        return action
    }

    /// On each connect: the habit runs from every pixie's habits (each habit's latest run
    /// that is not queued), and the working chats' agents are asked for again.
    public func refresh() async {
        activityRequested = []
        let ids = pixies.pixies.map(\.id)
        _ = try? await live.read {
            var latest: [String: HabitRun] = [:]
            for id in ids {
                guard let habits = try? await self.api.pixieHabits(id) else { continue }
                for habit in habits {
                    if let run = habit.lastRun { latest[habit.id] = run }
                }
            }
            return latest
        } store: {
            runs = $0
        } replay: {
            apply($0)
        }
        await loadActivity(state())
    }

    /// Reads the tracked agents of each chat with a working pixie that were not asked for
    /// since the last connect; events keep them current from then on. The Mac app calls this
    /// when the state's `workingChats` change.
    public func loadActivity(_ state: IslandState) async {
        for chat in state.workingChats where !activityRequested.contains(chat) {
            activityRequested.insert(chat)
            try? await activity.load(session: chat)
        }
    }

    public func apply(_ event: Event) {
        live.record(event)
        switch event.body {
        case .habitRunUpdated(let run):
            // A queued run does not replace the latest one that ran.
            if run.outcome != .queued { runs[run.habitID] = run }
        case .habitUpdated(let habit):
            if let run = habit.lastRun, runs[habit.id]?.id != run.id {
                runs[habit.id] = run
            }
        case .habitDeleted(let id, _):
            runs[id] = nil
        case .pixieDeleted(let pixie):
            runs = runs.filter { $0.value.pixieID != pixie }
        case .sessionState(let state, _):
            guard let id = event.sessionID,
                pixies.pixies.contains(where: { $0.chatSessionID == id })
            else { return }
            pixieChats[id] = (state, event.ts)
        case .sessionDeleted(let id):
            pixieChats[id] = nil
            if seen.removeValue(forKey: id) != nil { saveSeen() }
        default:
            break
        }
    }

    func snapshot(fullScreen: Bool, pill: Bool) -> IslandSnapshot {
        let groups = chatPixies.allGroups
        let habitRuns = Array(runs.values)
        var agents: [String: [TrackedAgent]] = [:]
        for id in Array(groups.keys) + habitRuns.compactMap(\.sessionID) {
            agents[id] = activity.agents(session: id)
        }
        return IslandSnapshot(
            groups: groups, agents: agents, approvals: approvals.pending, habitRuns: habitRuns,
            pixies: pixies.pixies, teams: pixies.teams, chats: chats(), seen: seen,
            installedAt: installedAt, order: order, now: now(), shown: shown,
            fullScreen: fullScreen, pill: pill, awakeSince: startedAt)
    }

    /// Project chats and pixies' own chats count as normal (C4); habit runs and called
    /// pixies' sessions carry a pixie id but are not its chat.
    private func chats() -> [String: IslandChat] {
        let pixieChatIDs = Set(pixies.pixies.compactMap(\.chatSessionID))
        var chats: [String: IslandChat] = [:]
        for session in sessions.sessions.values {
            chats[session.id] = IslandChat(
                id: session.id, repo: session.repo, working: session.state.isWorking,
                updatedAt: session.updatedAt,
                isNormal: session.pixieID == nil || pixieChatIDs.contains(session.id))
        }
        for (id, live) in pixieChats {
            if let known = chats[id], known.updatedAt >= live.at { continue }
            chats[id] = IslandChat(
                id: id, repo: chats[id]?.repo, working: live.state.isWorking,
                updatedAt: live.at, isNormal: true)
        }
        return chats
    }

    private func saveSeen() {
        let text = seen.map { "\($0.key)=\($0.value.timeIntervalSince1970)" }.sorted()
            .joined(separator: "\n")
        store.set(text, forKey: Key.seen)
    }

    private static func readSeen(_ text: String?) -> [String: Date] {
        var seen: [String: Date] = [:]
        for line in (text ?? "").split(separator: "\n") {
            let parts = line.split(separator: "=", maxSplits: 1)
            guard parts.count == 2, let time = Double(parts[1]) else { continue }
            seen[String(parts[0])] = Date(timeIntervalSince1970: time)
        }
        return seen
    }
}
