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
    /// The lane it is drawn in, at most the cap.
    public let depth: Int
    public let lines: [BranchLaneLine]
    /// The lane its curve leaves from; its own lane past the cap, where it drops straight
    /// down; nil for a root.
    public let parentDepth: Int?
    /// Its parent's name, on rows past the cap only.
    public let fromParent: String?
    /// No children and no worktree, so it wears its parent's lane until it needs its own.
    public let plain: Bool
    /// "here" where the project folder is.
    public let label: String?

    public var id: String { branch.name }

    /// A lane's centre, from the graph's left edge.
    public static func x(_ depth: Int) -> Double { 14 + 14 * Double(depth) }

    /// The branch whose colour the row draws in: its parent's while it is plain, its own
    /// once it means something.
    public func lane(selected: Bool, chat: BranchChatStatus?) -> String {
        guard plain, !selected, chat == nil, let parent = branch.parent else {
            return branch.name
        }
        return parent
    }

    /// The row for VoiceOver: its branch, "here", its remote, its note and its chat's state.
    public func accessibilityLabel(status: BranchChatStatus?) -> String {
        let chat: String? =
            switch status {
            case .running: "chat running"
            case .needsYou: "chat needs you"
            case .idle: "chat idle"
            case nil: nil
            }
        let remote = branch.remote.map { "only on \($0)" }
        return [branch.name, label, remote, branch.behindNote, chat]
            .compactMap { $0 }.joined(separator: ", ")
    }
}

/// The branch map's rows, as A7 draws them (B96): depth first, each lane down to its last
/// child. `maxDepth` caps the indent (B131), rows past it naming their parent.
public struct BranchLanes: Sendable, Hashable {
    /// Where the small map and the picker stop indenting; the full tree has no cap.
    public static let indentCap = 3

    public let rows: [BranchLaneRow]
    /// The row with no parent, pinned over the rest.
    public let top: BranchLaneRow?
    public let rest: [BranchLaneRow]

    public init(map: BranchMap, maxDepth: Int? = nil) {
        let names = Set(map.branches.map(\.name))
        var children: [String: [BranchMap.Branch]] = [:]
        for branch in map.branches {
            if let parent = branch.parent, names.contains(parent) {
                children[parent, default: []].append(branch)
            }
        }
        var placed: [(branch: BranchMap.Branch, depth: Int)] = []
        var seen: Set<String> = []
        func visit(_ branch: BranchMap.Branch, _ depth: Int) {
            guard seen.insert(branch.name).inserted else { return }
            placed.append((branch, depth))
            for child in children[branch.name] ?? [] {
                visit(child, depth + 1)
            }
        }
        for branch in map.branches where branch.parent.map(names.contains) != true {
            visit(branch, 0)
        }
        // A loop the daemon should never send still shows.
        for branch in map.branches {
            visit(branch, 0)
        }

        func shown(_ depth: Int) -> Int { maxDepth.map { min(depth, $0) } ?? depth }
        var index: [String: Int] = [:]
        for (at, row) in placed.enumerated() {
            index[row.branch.name] = at
        }
        var lastChild: [String: Int] = [:]
        for (at, row) in placed.enumerated() {
            if let parent = row.branch.parent, let from = index[parent], from < at {
                lastChild[parent] = at
            }
        }
        var lines = Array(repeating: [BranchLaneLine](), count: placed.count)
        func add(_ at: Int, _ depth: Int, _ lane: String, fromMiddle: Bool) {
            lines[at].append(
                BranchLaneLine(
                    depth: min(depth, shown(placed[at].depth)), lane: lane, fromMiddle: fromMiddle))
        }
        for (at, row) in placed.enumerated() {
            guard let last = lastChild[row.branch.name] else { continue }
            add(at, row.depth, row.branch.name, fromMiddle: true)
            for between in (at + 1)..<max(last, at + 1) {
                add(between, row.depth, row.branch.name, fromMiddle: false)
            }
        }

        let rows = placed.enumerated().map { at, row in
            let branch = row.branch
            return BranchLaneRow(
                branch: branch, depth: shown(row.depth),
                lines: lines[at].sorted { $0.depth < $1.depth },
                parentDepth: row.depth == 0 ? nil : shown(row.depth - 1),
                fromParent: row.depth > shown(row.depth) ? branch.parent : nil,
                plain: branch.worktree == nil && children[branch.name] == nil
                    && branch.parent.map(names.contains) == true,
                label: branch.here ? "here" : nil)
        }
        let top = rows.first { $0.branch.parent == nil }
        self.rows = rows
        self.top = top
        rest = rows.filter { $0.id != top?.id }
    }

    /// The graph's width: the deepest lane and a lane's room after it.
    public var width: Double {
        BranchLaneRow.x(rows.map(\.depth).max() ?? 0) + 14
    }
}

/// The lane colours of a project's branches (B96, B131): the top row always grey, the others
/// the first colour no shown branch uses, cycling once all are in use. A plain branch takes
/// no colour until something asks for one (`BranchLaneRow.lane`). A branch keeps its colour
/// for as long as it is on the map: the colours are kept, because giving them out again by
/// position would change them when the app starts or another branch appears.
public struct LaneColors {
    public static let palette: [ThemedColor] = {
        typealias Lane = DesignTokens.Colors.Lane
        return [
            Lane.root, Lane.violet, Lane.teal, Lane.blue, Lane.pink, Lane.lime, Lane.orange,
            Lane.yellow,
        ]
    }()

    private var assigned: [String: Int]
    private var cycle = 0
    /// Keeps the colours of the branches on the map for the next run.
    private let save: (([String: Int]) -> Void)?

    public init(saved: [String: Int] = [:], save: (([String: Int]) -> Void)? = nil) {
        let colours = 1..<Self.palette.count
        assigned = saved.filter { colours.contains($0.value) }
        self.save = save
    }

    public static func color(_ index: Int) -> ThemedColor {
        palette[index % palette.count]
    }

    /// Gives the branches that draw a lane of their own their colours.
    public mutating func assign(_ map: BranchMap) {
        let parents = Set(map.branches.compactMap(\.parent))
        for branch in map.branches where branch.worktree != nil || parents.contains(branch.name) {
            _ = index(of: branch.name, in: map)
        }
    }

    /// The branch's palette index, given the first time: 0 for the top row, nil for a branch
    /// not on the map.
    public mutating func index(of branch: String, in map: BranchMap) -> Int? {
        guard map.branch(branch) != nil else { return nil }
        guard branch != map.top?.name else { return 0 }
        return assigned[branch] ?? give(branch, in: map)
    }

    private mutating func give(_ branch: String, in map: BranchMap) -> Int {
        let used = Set(map.branches.compactMap { assigned[$0.name] })
        let colours = 1..<Self.palette.count
        let index =
            colours.first { !used.contains($0) }
            ?? {
                defer { cycle += 1 }
                return cycle % colours.count + 1
            }()
        assigned[branch] = index
        save?(assigned.filter { name, _ in map.branch(name) != nil })
        return index
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
        // Filed once, since a project can have hundreds of branches.
        var byName: [String: [Session]] = [:]
        var byFolder: [String: [Session]] = [:]
        for session in live {
            if let name = ChatPlace.of(session, repo: repo)?.branchName {
                byName[name, default: []].append(session)
            }
            if let path = session.worktreePath {
                byFolder[path, default: []].append(session)
            }
        }
        let claudeFolders = Set(chats.map(\.cwd))
        var found: [String: BranchChatStatus] = [:]
        for branch in branches {
            let path = branch.worktree?.path
            let named = byName[branch.name] ?? []
            let foldered = path.flatMap { byFolder[$0] } ?? []
            let claude = path.map(claudeFolders.contains) ?? false
            guard !named.isEmpty || !foldered.isEmpty || claude else { continue }
            found[branch.name] =
                (named + foldered).map { BranchChatStatus(tone($0)) }.max() ?? .idle
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
