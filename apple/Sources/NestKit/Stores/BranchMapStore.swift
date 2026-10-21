import Foundation
import Observation

/// The branch maps of the projects the sidebar shows (B96), read while it shows them (the
/// chat rows colour their branches even with the map closed), again on each
/// `repo.branches_changed` and on each connect. Keeps each project's lane colours, and
/// whether its map is open, for as long as the app runs.
@MainActor @Observable
public final class BranchMapStore {
    public private(set) var maps: [String: BranchMap] = [:]
    /// The project the sidebar shows; nil for none or a plain folder.
    public private(set) var shown: String?
    private var colors: [String: LaneColors] = [:]
    private var open: Set<String> = []

    let api: any NestAPI
    /// The latest refresh an event started; each waits for the one before it.
    @ObservationIgnored private(set) var refreshing: Task<Void, Never>?

    public init(api: any NestAPI) {
        self.api = api
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
        colors[repo, default: LaneColors()].assign(map)
        maps[repo] = map
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
        let previous = refreshing
        refreshing = Task {
            await previous?.value
            await load(repo)
        }
    }

    public func map(_ repo: String) -> BranchMap? {
        maps[repo]
    }

    public func lanes(_ repo: String) -> BranchLanes? {
        maps[repo].map { BranchLanes(map: $0) }
    }

    /// The new chat's "Work on" picker, once the map is loaded.
    public func picker(_ repo: String) -> PlacePicker? {
        maps[repo].map { PlacePicker(map: $0) }
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

    public func toggle(_ repo: String) {
        if open.remove(repo) == nil {
            open.insert(repo)
        }
    }
}
