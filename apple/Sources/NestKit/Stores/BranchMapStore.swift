import Foundation
import Observation

/// A project's reload of its remotes (B131), which outlives the map being open.
public struct RemotesReload: Sendable, Hashable {
    public var running = false
    public var failures: [Failure] = []

    public init() {}

    /// Remotes that failed the same way, with the reason.
    public struct Failure: Sendable, Hashable, Identifiable {
        public let remotes: String
        public let reason: String

        public var id: String { remotes }
    }

    /// Each reason once, naming the remotes it hit.
    public static func failures(of report: RemotesRefresh) -> [Failure] {
        var reasons: [String] = []
        var named: [String: [String]] = [:]
        for remote in report.remotes {
            guard let error = remote.error else { continue }
            if named[error] == nil {
                reasons.append(error)
            }
            named[error, default: []].append(remote.name)
        }
        return reasons.map {
            Failure(remotes: named[$0, default: []].joined(separator: ", "), reason: $0)
        }
    }
}

/// The branch maps of the projects the sidebar shows (B96), read while it shows them (the
/// chat rows colour their branches even with the map closed), again on each
/// `repo.branches_changed`, on each connect and each time a map or picker opens. Keeps each
/// project's lane colours, its reload and whether its map is open, for as long as the app
/// runs. The lanes are worked out once per read, for projects with hundreds of branches.
@MainActor @Observable
public final class BranchMapStore {
    public private(set) var maps: [String: BranchMap] = [:]
    /// The project the sidebar shows; nil for none or a plain folder.
    public private(set) var shown: String?
    private var drawn: [String: Drawn] = [:]
    private var reloads: [String: RemotesReload] = [:]
    /// Reading a colour may give one, which no view needs to redraw for.
    @ObservationIgnored private var colors: [String: LaneColors] = [:]
    private var open: Set<String> = []

    let api: any NestAPI
    /// Where each project's colours are kept between runs; per client, as the colours are.
    @ObservationIgnored private let store: any KeyValueStore
    @ObservationIgnored private let now: () -> Date
    /// Until when each project's rows ignore clicks.
    @ObservationIgnored private var heldPicks: [String: Date] = [:]
    /// The latest refresh an event started; each waits for the one before it.
    @ObservationIgnored private(set) var refreshing: Task<Void, Never>?

    public init(api: any NestAPI, store: any KeyValueStore, now: @escaping () -> Date = { Date() })
    {
        self.api = api
        self.store = store
        self.now = now
    }

    /// How long rows ignore clicks after a pick that changed the list: past the slowest double
    /// click, as a second click after the pause lands on another row.
    public static let pickPause = 0.6

    /// A pick is changing the list under the pointer, or just did: a second click of a double
    /// click would land on whichever row moved there, so the project's rows ignore it.
    public func picksHeld(_ repo: String) -> Bool {
        heldPicks[repo].map { $0 > now() } ?? false
    }

    /// Runs such a pick, whole, unless one holds. A failed pick ends the hold the same way.
    public func holdPicks(_ repo: String, _ pick: () async throws -> Void) async throws {
        guard !picksHeld(repo) else { return }
        heldPicks[repo] = .distantFuture
        defer { heldPicks[repo] = now().addingTimeInterval(Self.pickPause) }
        try await pick()
    }

    static func colorsKey(_ repo: String) -> String { "nest.laneColors.\(repo)" }

    /// The project's colours as the last run left them; bad storage only forgets them.
    private func savedColors(_ repo: String) -> LaneColors {
        let key = Self.colorsKey(repo)
        let saved = store.string(forKey: key).flatMap {
            try? JSONDecoder().decode([String: Int].self, from: Data($0.utf8))
        }
        return LaneColors(saved: saved ?? [:]) { [store] colours in
            let data = try? JSONEncoder().encode(colours)
            store.set(data.flatMap { String(data: $0, encoding: .utf8) }, forKey: key)
        }
    }

    /// A map's rows, capped for the small map and the picker, and whole for the full tree.
    private struct Drawn {
        let lanes: BranchLanes
        let tree: BranchLanes
        let picker: PlacePicker

        init(_ map: BranchMap) {
            lanes = BranchLanes(map: map, maxDepth: BranchLanes.indentCap)
            tree = BranchLanes(map: map)
            picker = PlacePicker(lanes: lanes)
        }
    }

    /// Follows the project the sidebar shows, reading its map.
    public func show(_ repo: String?) async {
        shown = repo
        if let repo {
            await load(repo)
        }
    }

    /// Reads the project's map; a failure keeps the one it had, for the next event or
    /// connect to read again.
    public func load(_ repo: String) async {
        guard let map = try? await api.repoBranchMap(repo) else { return }
        colors[repo, default: savedColors(repo)].assign(map)
        guard maps[repo] != map else { return }
        maps[repo] = map
        drawn[repo] = Drawn(map)
    }

    /// Reads every loaded map again, and the shown project's.
    public func reload() async {
        for repo in Set(maps.keys).union(shown.map { [$0] } ?? []).sorted() {
            await load(repo)
        }
    }

    public func apply(_ event: Event) {
        guard case .branchesChanged(let repo) = event.body, maps[repo] != nil || shown == repo
        else { return }
        refresh(repo)
    }

    /// Reads the project's map again in the background, after the reads before it. The map
    /// must be right every time it opens, and a branch made in a terminal may have no event.
    public func refresh(_ repo: String) {
        let previous = refreshing
        refreshing = Task {
            await previous?.value
            await load(repo)
        }
    }

    /// The project's reload: the map at once, since a dead remote can hold the fetch for
    /// minutes, then the fetch, then the map again. The map stays usable throughout.
    public func refreshRemotes(_ repo: String) async throws {
        guard !reload(of: repo).running else { return }
        reloads[repo, default: RemotesReload()].running = true
        await load(repo)
        var finished = RemotesReload()
        defer { reloads[repo] = finished }
        let report = try await api.refreshRemotes(repo)
        await load(repo)
        finished.failures = RemotesReload.failures(of: report)
    }

    public func reload(of repo: String) -> RemotesReload {
        reloads[repo] ?? RemotesReload()
    }

    public func dismissFailures(of repo: String) {
        reloads[repo] = nil
    }

    /// Makes the local branch for a remote-only one, and reads the map with it.
    public func track(_ remote: BranchMap.RemoteBranch, in repo: String) async throws -> String {
        let branch = try await api.trackRemoteBranch(
            repo, remote: remote.remote, branch: remote.name)
        await load(repo)
        return branch
    }

    public func map(_ repo: String) -> BranchMap? {
        maps[repo]
    }

    /// The small map's rows, the indent capped.
    public func lanes(_ repo: String) -> BranchLanes? {
        drawn[repo]?.lanes
    }

    /// The full tree's rows, every level.
    public func tree(_ repo: String) -> BranchLanes? {
        drawn[repo]?.tree
    }

    /// The new chat's "Work on" picker, once the map is loaded.
    public func picker(_ repo: String) -> PlacePicker? {
        drawn[repo]?.picker
    }

    public func color(of branch: String, in repo: String) -> ThemedColor? {
        guard let map = maps[repo], let index = colors[repo]?.index(of: branch, in: map) else {
            return nil
        }
        return LaneColors.color(index)
    }

    /// The colour of the branch a chat works on, for its row's second line.
    public func color(of place: ChatPlace, in repo: String) -> ThemedColor? {
        maps[repo]?.branch(for: place).flatMap { color(of: $0.name, in: repo) }
    }

    public func chats(
        in repo: String, sessions: [Session], claudeChats: [ClaudeChat], repo info: Repo?,
        tone: (Session) -> StatusTone
    ) -> [String: BranchChatStatus] {
        maps[repo]?.chats(sessions: sessions, claudeChats: claudeChats, repo: info, tone: tone)
            ?? [:]
    }

    public func isOpen(_ repo: String) -> Bool {
        open.contains(repo)
    }

    /// Opens or closes the project's map; opening reads it again.
    public func toggle(_ repo: String) {
        if open.remove(repo) == nil {
            open.insert(repo)
            refresh(repo)
        }
    }
}
