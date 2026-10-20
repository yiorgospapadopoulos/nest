import Foundation

/// A vertical line through a branch map row (B96): the lane of a branch on its way down to
/// its last child, from the row's top or, in the branch's own row, from its node.
public struct BranchLaneLine: Sendable, Hashable {
    public let depth: Int
    /// The branch the line belongs to, for its colour.
    public let lane: String
    public let fromMiddle: Bool

    public init(depth: Int, lane: String, fromMiddle: Bool) {
        self.depth = depth
        self.lane = lane
        self.fromMiddle = fromMiddle
    }
}

/// One row of the branch map: its branch's node in its lane, the lines passing through,
/// and the curve from its parent's lane into the node.
public struct BranchLaneRow: Sendable, Hashable, Identifiable {
    public static let height = 34.0

    public let branch: BranchMap.Branch
    public let depth: Int
    public let lines: [BranchLaneLine]
    /// "here" where the project folder is.
    public let label: String?

    public var id: String { branch.name }

    /// The lane the curve into the node starts from; nil for a root.
    public var parentDepth: Int? { depth > 0 ? depth - 1 : nil }

    /// A lane's centre, from the graph's left edge.
    public static func x(_ depth: Int) -> Double { 14 + 14 * Double(depth) }

    /// What a click on the row does (A8): its tooltip.
    public var newChatHelp: String {
        let action = action
        return action.prefix(1).uppercased() + action.dropFirst()
    }

    /// Where its click starts the chat (`BranchMap.Branch.newChatChoice`), in words.
    private var action: String {
        if branch.here {
            "new chat in the project folder"
        } else if branch.worktree != nil {
            "new chat in this worktree"
        } else {
            "new chat working on \(branch.name)"
        }
    }

    /// The row for VoiceOver: its branch, "here", what a click does, and its chat's state.
    public func accessibilityLabel(status: BranchChatStatus?) -> String {
        let chat: String? =
            switch status {
            case .running: "chat running"
            case .needsYou: "chat needs you"
            case .idle: "chat idle"
            case nil: nil
            }
        return ([branch.name, label, action, chat].compactMap { $0 }).joined(separator: ", ")
    }
}

/// The branch map's rows, as A7 draws them (B96).
public struct BranchLanes: Sendable, Hashable {
    public let rows: [BranchLaneRow]
    public let worktrees: Int

    public init(map: BranchMap) {
        var placed: [(branch: BranchMap.Branch, depth: Int)] = []
        var seen: Set<String> = []
        func visit(_ branch: BranchMap.Branch, _ depth: Int) {
            guard seen.insert(branch.name).inserted else { return }
            placed.append((branch, depth))
            for child in map.children(of: branch.name) {
                visit(child, depth + 1)
            }
        }
        let names = Set(map.branches.map(\.name))
        for branch in map.branches where branch.parent.map(names.contains) != true {
            visit(branch, 0)
        }
        // A loop the daemon should never send still shows.
        for branch in map.branches {
            visit(branch, 0)
        }

        var lines = Array(repeating: [BranchLaneLine](), count: placed.count)
        for (index, row) in placed.enumerated() {
            let children = placed.indices.filter {
                $0 > index && placed[$0].branch.parent == row.branch.name
            }
            guard let last = children.last else { continue }
            lines[index].append(
                BranchLaneLine(depth: row.depth, lane: row.branch.name, fromMiddle: true))
            for between in (index + 1)..<last {
                lines[between].append(
                    BranchLaneLine(depth: row.depth, lane: row.branch.name, fromMiddle: false))
            }
        }

        rows = placed.enumerated().map { index, row in
            BranchLaneRow(
                branch: row.branch, depth: row.depth,
                lines: lines[index].sorted { $0.depth < $1.depth },
                label: row.branch.here ? "here" : nil)
        }
        worktrees = placed.filter { $0.depth > 0 && $0.branch.worktree != nil }.count
    }

    /// The graph's width: the deepest lane and a lane's room after it.
    public var width: Double {
        BranchLaneRow.x(rows.map(\.depth).max() ?? 0) + 14
    }

    /// The header's count: "5 worktrees".
    public var count: String {
        "\(worktrees) worktree\(worktrees == 1 ? "" : "s")"
    }
}

/// The lane colours of a project's branches (B96): the default branch always grey, the
/// others in the palette's order. A branch keeps its colour while the app runs; a new one
/// takes the first colour no shown branch uses, cycling once all are in use.
public struct LaneColors: Sendable {
    public static let palette: [ThemedColor] = {
        typealias Lane = DesignTokens.Colors.Lane
        return [
            Lane.root, Lane.violet, Lane.teal, Lane.blue, Lane.pink, Lane.lime, Lane.orange,
            Lane.yellow,
        ]
    }()

    private var assigned: [String: Int] = [:]
    private var cycle = 0

    public init() {}

    public static func color(_ index: Int) -> ThemedColor {
        palette[index % palette.count]
    }

    /// Gives the map's new branches their colours.
    public mutating func assign(_ map: BranchMap) {
        var used = Set(map.branches.compactMap { assigned[$0.name] })
        for branch in map.branches
        where branch.name != map.defaultBranch && assigned[branch.name] == nil {
            let colours = 1..<Self.palette.count
            let index =
                colours.first { !used.contains($0) }
                ?? {
                    defer { cycle += 1 }
                    return cycle % colours.count + 1
                }()
            assigned[branch.name] = index
            used.insert(index)
        }
    }

    /// The branch's palette index: 0 for the default branch, nil for one never assigned.
    public func index(of branch: String, in map: BranchMap) -> Int? {
        branch == map.defaultBranch ? 0 : assigned[branch]
    }
}

/// A branch map row's chat dot: running, needing the user, or idle (B96).
public enum BranchChatStatus: Sendable, Hashable, Comparable {
    case idle, running, needsYou

    public init(_ tone: StatusTone) {
        self =
            switch tone {
            case .running: .running
            case .waiting: .needsYou
            default: .idle
            }
    }
}

extension BranchMap {
    /// The dot of each branch with chats, by branch name (B96): the most urgent of the Nest
    /// chats in its worktree folder or on it by name (in-place chats are on the folder's
    /// branch), and idle for the Claude Code chats in its worktree. Archived chats are left
    /// out.
    public func chats(
        sessions: [Session], claudeChats: [ClaudeChat], repo: Repo?,
        tone: (Session) -> StatusTone
    ) -> [String: BranchChatStatus] {
        let live = sessions.filter { !$0.isArchived }
        let chats = claudeChats.filter { !$0.archived && $0.worktree != nil }
        var found: [String: BranchChatStatus] = [:]
        for branch in branches {
            let path = branch.worktree?.path
            let nest = live.filter {
                (path != nil && $0.worktreePath == path)
                    || ChatPlace.of($0, repo: repo)?.branchName == branch.name
            }
            let claude = chats.contains { path != nil && $0.cwd == path }
            guard !nest.isEmpty || claude else { continue }
            found[branch.name] = nest.map { BranchChatStatus(tone($0)) }.max() ?? .idle
        }
        return found
    }
}

extension ChatPlace {
    /// The branch it works on, when known: the worktree's or the folder's.
    var branchName: String? {
        switch self {
        case .worktree(let name, _): name
        case .projectFolder(let branch, _): branch
        }
    }
}
