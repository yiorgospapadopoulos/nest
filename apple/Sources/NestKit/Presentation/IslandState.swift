import Foundation

// What the island around the notch shows (B114): the working pixies on the left, the ones
// that finished or need the user on the right, Nightshade when nothing of a pixie works.

/// Where the island lists its pixies: newest first or oldest first, on both sides and in
/// the list.
public enum IslandOrder: String, Sendable, CaseIterable {
    case newestFirst = "newest"
    case oldestFirst = "oldest"
}

/// How a pixie on the island stands.
public enum IslandStatus: String, Sendable, Hashable {
    case working
    case needsYou
    /// Needs the user, but its chat was opened since: calm.
    case seen
    case done, failed, interrupted

    /// The word on the right of its row.
    public var word: String {
        switch self {
        case .working: "Working"
        case .needsYou, .seen: "Needs you"
        case .done: "Done"
        case .failed: "Failed"
        case .interrupted: "Interrupted"
        }
    }

    /// Wants the user's eye: orange on the island and in the +N.
    public var isAlert: Bool {
        self == .needsYou || self == .failed || self == .interrupted
    }
}

/// What an entry draws: a pixie's sprite, or a team's two by two icon.
public enum IslandFigure: Sendable, Hashable {
    case pixie(Pixie)
    /// The team, its leader's colour (`#RRGGBB`) and the icon's four cells.
    case team(PixieTeam, color: String?, cells: [TeamIconCell])
}

/// The chat a click opens: the chat the work happens in.
public enum IslandPlace: Sendable, Hashable {
    /// A project chat, opened with `reveal(chat:in:)`; the repo is nil while unknown.
    case chat(session: String, repo: String?)
    /// A pixie's own chat, where it called another pixie.
    case pixieChat(pixie: String, session: String)
    /// A habit run's own session, read-only.
    case habitRun(session: String)

    public var sessionID: String {
        switch self {
        case .chat(let session, _), .pixieChat(_, let session), .habitRun(let session): session
        }
    }
}

/// A pixie or team on the island and in its list.
public struct IslandEntry: Sendable, Hashable, Identifiable {
    /// Stable across updates: "<session>/<group entry id>", or "habit:<session>".
    public let id: String
    public let figure: IslandFigure
    /// The pixie's or the team's name.
    public let label: String
    public let place: IslandPlace
    /// The pending approval it waits on, for needs you and seen.
    public let approvalID: String?
    public let status: IslandStatus
    /// What orders it: when it started, finished, asked, or was seen.
    public let since: Date
    /// The row's second line: what it does right now.
    public let activity: String

    public init(
        id: String, figure: IslandFigure, label: String, place: IslandPlace,
        approvalID: String?, status: IslandStatus, since: Date, activity: String
    ) {
        self.id = id
        self.figure = figure
        self.label = label
        self.place = place
        self.approvalID = approvalID
        self.status = status
        self.since = since
        self.activity = activity
    }
}

/// Nightshade on the left while no pixie works.
public enum NightshadeMode: Sendable, Hashable {
    /// Blinks and flutters now and then.
    case idle
    /// Hops: a chat without a pixie works.
    case working
    /// Nothing ran for `IslandState.sleepAfter`.
    case asleep
}

/// A chat the island knows of, apart from its pixies: whether it works and its repo.
public struct IslandChat: Sendable, Hashable {
    public var id: String
    public var repo: String?
    public var working: Bool
    /// When its state last changed.
    public var updatedAt: Date
    /// A chat without a pixie call of its own: a project chat, or a pixie's own chat when
    /// the user talks to it (C4). Only these make Nightshade hop.
    public var isNormal: Bool

    public init(id: String, repo: String?, working: Bool, updatedAt: Date, isNormal: Bool) {
        self.id = id
        self.repo = repo
        self.working = working
        self.updatedAt = updatedAt
        self.isNormal = isNormal
    }
}

/// Everything the island is computed from, at one moment.
public struct IslandSnapshot: Sendable {
    /// Each chat's pixie group, by chat session id.
    public var groups: [String: [ChatPixieEntry]]
    /// The tracked agents of the chats, by session id, for the rows' activity.
    public var agents: [String: [TrackedAgent]]
    /// Pending approvals.
    public var approvals: [Approval]
    /// The latest run of each habit (running or finished).
    public var habitRuns: [HabitRun]
    public var pixies: [Pixie]
    public var teams: [PixieTeam]
    /// By session id.
    public var chats: [String: IslandChat]
    /// When each chat was last opened or its pixie clicked, by session id.
    public var seen: [String: Date]
    /// When the island was first shown on this Mac: older finishes never show.
    public var installedAt: Date
    public var order: IslandOrder
    public var now: Date
    /// The island is turned on in its settings.
    public var shown: Bool
    /// No notch: the pill in the menu bar.
    public var pill: Bool
    /// When the island started: Nightshade stays awake for a while after it.
    public var awakeSince: Date?

    public init(
        groups: [String: [ChatPixieEntry]] = [:], agents: [String: [TrackedAgent]] = [:],
        approvals: [Approval] = [], habitRuns: [HabitRun] = [], pixies: [Pixie] = [],
        teams: [PixieTeam] = [], chats: [String: IslandChat] = [:], seen: [String: Date] = [:],
        installedAt: Date, order: IslandOrder = .newestFirst, now: Date, shown: Bool = true,
        pill: Bool = false, awakeSince: Date? = nil
    ) {
        self.groups = groups
        self.agents = agents
        self.approvals = approvals
        self.habitRuns = habitRuns
        self.awakeSince = awakeSince
        self.pixies = pixies
        self.teams = teams
        self.chats = chats
        self.seen = seen
        self.installedAt = installedAt
        self.order = order
        self.now = now
        self.shown = shown
        self.pill = pill
    }
}

/// What the island shows now.
public struct IslandState: Sendable, Hashable {
    /// Working pixies, in order.
    public var left: [IslandEntry]
    /// Done, needs you, seen, failed and interrupted pixies, in order.
    public var right: [IslandEntry]
    /// Every entry, in order, for the hover list.
    public var list: [IslandEntry]
    /// Nightshade on the left, when no pixie works there.
    public var nightshade: NightshadeMode?
    /// The pill's Bluebell resting on the right while nothing at all shows.
    public var restingBluebell: Bool
    /// Nothing to draw and no hover target.
    public var isHidden: Bool

    public init(
        left: [IslandEntry], right: [IslandEntry], list: [IslandEntry],
        nightshade: NightshadeMode?, restingBluebell: Bool, isHidden: Bool
    ) {
        self.left = left
        self.right = right
        self.list = list
        self.nightshade = nightshade
        self.restingBluebell = restingBluebell
        self.isHidden = isHidden
    }

    public static let empty = IslandState(
        left: [], right: [], list: [], nightshade: nil, restingBluebell: false, isHidden: true)

    /// Nightshade falls asleep after this long with nothing running.
    public static let sleepAfter: TimeInterval = 120

    /// The chats whose tracked agents the working rows read.
    public var workingChats: [String] {
        var ids: [String] = []
        for entry in list where entry.status == .working && !ids.contains(entry.place.sessionID) {
            ids.append(entry.place.sessionID)
        }
        return ids
    }

    public static func make(_ snapshot: IslandSnapshot) -> IslandState {
        guard snapshot.shown else { return .empty }
        let entries = Builder(snapshot).entries()
        let list = sorted(entries, snapshot.order)
        let left = list.filter { $0.status == .working }
        let right = list.filter { $0.status != .working }
        return IslandState(
            left: left, right: right, list: list,
            nightshade: left.isEmpty ? nightshade(snapshot, entries: entries) : nil,
            restingBluebell: snapshot.pill && entries.isEmpty, isHidden: false)
    }

    /// Newest first sorts by `since` descending, oldest first ascending; ties by id.
    static func sorted(_ entries: [IslandEntry], _ order: IslandOrder) -> [IslandEntry] {
        entries.sorted { a, b in
            if a.since != b.since {
                return order == .newestFirst ? a.since > b.since : a.since < b.since
            }
            return a.id < b.id
        }
    }

    private static func nightshade(_ snapshot: IslandSnapshot, entries: [IslandEntry])
        -> NightshadeMode
    {
        let normal = snapshot.chats.values.filter(\.isNormal)
        if normal.contains(where: \.working) { return .working }
        let calls = snapshot.groups.values.flatMap { $0.flatMap(\.calls) }
        // A call waiting on the user still runs.
        if calls.contains(where: { $0.state == .running })
            || snapshot.habitRuns.contains(where: { $0.outcome == .running })
        {
            return .idle
        }
        var last: [Date] = normal.map(\.updatedAt) + [snapshot.awakeSince].compactMap(\.self)
        for call in calls {
            last.append(call.finishedAt ?? call.startedAt)
        }
        for run in snapshot.habitRuns {
            if let time = run.endedAt ?? run.startedAt { last.append(time) }
        }
        guard let latest = last.max() else { return .asleep }
        return snapshot.now.timeIntervalSince(latest) >= sleepAfter ? .asleep : .idle
    }
}

/// Turns a snapshot's groups and habit runs into entries; idle ones are left out.
private struct Builder {
    let snapshot: IslandSnapshot
    let blocking: [Approval]

    init(_ snapshot: IslandSnapshot) {
        self.snapshot = snapshot
        blocking = snapshot.approvals.filter {
            $0.status == .pending && Self.blockingKinds.contains($0.kind)
        }
    }

    /// What stops a call until the user answers.
    static let blockingKinds: Set<ApprovalKind> = [.permission, .question, .plan]

    func entries() -> [IslandEntry] {
        var entries: [IslandEntry] = []
        for (session, group) in snapshot.groups {
            for entry in group {
                if let made = self.entry(entry, session: session) { entries.append(made) }
            }
        }
        for run in snapshot.habitRuns {
            if let made = habitEntry(run) { entries.append(made) }
        }
        return entries
    }

    private func entry(_ entry: ChatPixieEntry, session: String) -> IslandEntry? {
        guard let figure = figure(of: entry), let latest = entry.calls.first else { return nil }
        let calls = Set(entry.calls.map(\.toolUseID))
        let approvals = blocking.filter { $0.call.map(calls.contains) == true }
        let place = place(session: session, approvals: approvals)
        let label: String =
            switch figure {
            case .pixie(let pixie): pixie.name
            case .team(let team, _, _): team.name
            }
        let state = status(
            session: session, approvals: approvals, state: entry.state,
            finished: latest.finishedAt ?? latest.startedAt, started: latest.startedAt)
        guard let state else { return nil }
        let activity =
            state.status == .working
            ? workingActivity(
                session: session, call: latest.toolUseID, team: entry.kind == .team)
            : state.activity
        return IslandEntry(
            id: "\(session)/\(entry.id)", figure: figure, label: label, place: place,
            approvalID: state.approval?.id, status: state.status, since: state.since,
            activity: activity)
    }

    private func habitEntry(_ run: HabitRun) -> IslandEntry? {
        guard let session = run.sessionID,
            let pixie = snapshot.pixies.first(where: { $0.id == run.pixieID })
        else { return nil }
        let callState: PixieCallState
        switch run.outcome {
        case .running: callState = .running
        case .reported, .quiet: callState = .done
        case .failed, .stalled, .timedOut: callState = .failed
        case .queued, .skipped, .unknown: return nil
        }
        let approvals = blocking.filter { $0.sessionID == session }
        let started = run.startedAt ?? run.dueAt ?? snapshot.installedAt
        guard
            let state = status(
                session: session, approvals: approvals, state: callState,
                finished: run.endedAt ?? started, started: started)
        else { return nil }
        let activity =
            state.status == .working
            ? snapshot.agents[session]?.first(where: \.isMain)?.activity ?? "Working"
            : state.activity
        return IslandEntry(
            id: "habit:\(session)", figure: .pixie(pixie), label: pixie.name,
            place: .habitRun(session: session), approvalID: state.approval?.id,
            status: state.status, since: state.since, activity: activity)
    }

    private struct Standing {
        var status: IslandStatus
        var since: Date
        var approval: Approval?
        /// The row's line, apart from working, whose line comes from its agents.
        var activity: String
    }

    /// Needs you while a blocking approval waits (seen once the chat was opened after it
    /// came), else working while the call runs, else done, failed or interrupted when it
    /// finished after the chat was last seen and after the island was first shown.
    private func status(
        session: String, approvals: [Approval], state: PixieCallState, finished: Date,
        started: Date
    ) -> Standing? {
        let seen = snapshot.seen[session]
        if let first = approvals.min(by: { $0.createdAt < $1.createdAt }) {
            let fresh = approvals.filter { approval in
                seen.map { approval.createdAt > $0 } ?? true
            }
            if let asking = fresh.min(by: { $0.createdAt < $1.createdAt }) {
                return Standing(
                    status: .needsYou, since: asking.createdAt, approval: asking,
                    activity: Self.line(asking))
            }
            return Standing(
                status: .seen, since: seen ?? first.createdAt, approval: first,
                activity: Self.line(first))
        }
        let ended: IslandStatus
        switch state {
        case .running:
            return Standing(status: .working, since: started, approval: nil, activity: "")
        case .done: ended = .done
        case .failed: ended = .failed
        case .interrupted: ended = .interrupted
        case .unknown: return nil
        }
        guard finished > snapshot.installedAt, seen.map({ finished > $0 }) ?? true else {
            return nil
        }
        let line = ended == .done ? "Finished" : ended.word
        return Standing(status: ended, since: finished, approval: nil, activity: line)
    }

    private static func line(_ approval: Approval) -> String {
        let line = NeedsYouLine.of(approval)
        return line.detail.map { "\(line.kind) · \($0)" } ?? line.kind
    }

    /// The call's live activity, else its description, else "Working"; a team's is the
    /// most recently started running member's (an agent inside the leader's call).
    private func workingActivity(session: String, call: String, team: Bool) -> String {
        let agents = snapshot.agents[session] ?? []
        let own = agents.first { $0.id == call }
        if team {
            let inside = agents.filter {
                $0.status == .running && $0.activity != nil
                    && Self.descends($0, from: call, in: agents)
            }
            if let member = inside.max(by: {
                ($0.startedAt ?? .distantPast) < ($1.startedAt ?? .distantPast)
            }), let activity = member.activity {
                return activity
            }
        }
        return own?.activity ?? own?.description ?? "Working"
    }

    private static func descends(
        _ agent: TrackedAgent, from call: String, in agents: [TrackedAgent]
    )
        -> Bool
    {
        var parent = agent.parent
        var hops = 0
        while let id = parent, hops < agents.count + 1 {
            if id == call { return true }
            parent = agents.first { $0.id == id }?.parent
            hops += 1
        }
        return false
    }

    private func figure(of entry: ChatPixieEntry) -> IslandFigure? {
        switch entry.kind {
        case .pixie:
            return snapshot.pixies.first { $0.id == entry.pixieID }.map(IslandFigure.pixie)
        case .team:
            guard let team = snapshot.teams.first(where: { $0.id == entry.teamID }) else {
                return nil
            }
            return .team(
                team, color: team.leaderColor(among: snapshot.pixies),
                cells: TeamIcon.cells(of: entry, pixies: snapshot.pixies))
        case .unknown:
            return nil
        }
    }

    /// A pixie's own chat opens on its pane; a project chat in its project.
    private func place(session: String, approvals: [Approval]) -> IslandPlace {
        if let owner = snapshot.pixies.first(where: { $0.chatSessionID == session }) {
            return .pixieChat(pixie: owner.id, session: session)
        }
        let repo = snapshot.chats[session]?.repo ?? approvals.first?.repo
        if let repo, let pixie = Pixie.id(ofRepo: repo) {
            return .pixieChat(pixie: pixie, session: session)
        }
        return .chat(session: session, repo: repo)
    }
}
