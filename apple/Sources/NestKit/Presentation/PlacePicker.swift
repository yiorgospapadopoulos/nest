import Foundation

/// A vertical piece of a picker row's lane (B96): from the row's top or its middle, to its
/// bottom or its middle.
public struct PlacePickerLine: Sendable, Hashable {
    public let depth: Int
    /// The branch the line belongs to, for its colour.
    public let lane: String
    public let fromTop: Bool
    public let toBottom: Bool

    public init(depth: Int, lane: String, fromTop: Bool, toBottom: Bool) {
        self.depth = depth
        self.lane = lane
        self.fromTop = fromTop
        self.toBottom = toBottom
    }
}

/// One row of the "Work on" picker (P1): a branch, the new worktree from it, or a worktree.
public struct PlacePickerRow: Sendable, Hashable, Identifiable {
    public static let height = 30.0

    public enum Kind: Sendable, Hashable {
        /// The branch the project folder is on: works in place.
        case folder
        /// Another branch: works on that branch itself.
        case branch
        case newWorktree
        case worktree
    }

    public let kind: Kind
    /// The row's branch; for a new worktree, the branch it starts from.
    public let branch: String
    public let depth: Int
    public let lines: [PlacePickerLine]
    /// The lane the curve into a worktree's node starts from; nil for the others.
    public let parentDepth: Int?
    /// What choosing it sets.
    public let choice: NewChatChoice

    public var id: String { kind == .newWorktree ? "new:\(branch)" : branch }

    public var title: String {
        kind == .newWorktree ? "New worktree from \(branch)" : branch
    }

    /// The quiet words after a branch's name.
    public var detail: String? {
        switch kind {
        case .folder: "project folder"
        case .branch: "branch"
        case .newWorktree, .worktree: nil
        }
    }

    public var accessibilityLabel: String {
        switch kind {
        case .folder: "Work on \(branch) in the project folder"
        case .branch: "Work on \(branch), branch"
        case .newWorktree: title
        case .worktree: "Work in worktree \(branch)"
        }
    }

    /// A lane's centre, from the graph's left edge.
    public static func x(_ depth: Int) -> Double { 12 + 14 * Double(depth) }
}

/// A branch and what a new chat can do from it, between dividers.
public struct PlacePickerBlock: Sendable, Hashable, Identifiable {
    public let rows: [PlacePickerRow]

    public var id: String { rows[0].branch }
}

/// Where a new chat can work, from the project's branch map (B96, P1): a block per branch
/// that is not itself a worktree, the folder's branch first, then the others in the map's
/// order. Each has the branch, "New worktree from" it, and the worktrees that come from it,
/// a worktree made from another worktree's branch one level further in.
public struct PlacePicker: Sendable, Hashable {
    public static let maxHeight = 330.0
    public static let dividerHeight = 9.0

    public let blocks: [PlacePickerBlock]

    public init(map: BranchMap) {
        var seen: Set<String> = []
        var blocks: [PlacePickerBlock] = []
        let heads = map.branches.filter { $0.worktree == nil }
        for head in heads.filter(\.here) + heads.filter({ !$0.here }) {
            seen.insert(head.name)
            var entries = [
                Entry(
                    kind: head.here ? .folder : .branch, branch: head.name, depth: 0,
                    parent: nil, choice: head.here ? .inPlace : .onBranch(head.name)),
                Entry(
                    kind: .newWorktree, branch: head.name, depth: 0, parent: 0,
                    choice: .newWorktree(from: head.name)),
            ]
            Self.addWorktrees(of: head.name, at: 1, under: 0, map: map, to: &entries, &seen)
            blocks.append(PlacePickerBlock(rows: Self.rows(entries)))
        }
        // A worktree whose parent is not shown, or a loop, still shows, in a block of its own.
        for branch in map.branches where branch.worktree != nil && !seen.contains(branch.name) {
            var entries: [Entry] = []
            Self.add(branch, at: 0, under: nil, map: map, to: &entries, &seen)
            blocks.append(PlacePickerBlock(rows: Self.rows(entries)))
        }
        self.blocks = blocks
    }

    /// The graph's width: the deepest lane and a lane's room after it.
    public var width: Double {
        PlacePickerRow.x(blocks.flatMap(\.rows).map(\.depth).max() ?? 0) + 14
    }

    /// As tall as the rows and dividers, up to about eleven rows; the rest scroll.
    public var height: Double {
        let rows = Double(blocks.map(\.rows.count).reduce(0, +)) * PlacePickerRow.height
        let dividers = Double(max(blocks.count - 1, 0)) * Self.dividerHeight
        return min(rows + dividers, Self.maxHeight)
    }

    private struct Entry {
        let kind: PlacePickerRow.Kind
        let branch: String
        let depth: Int
        /// The entry it hangs from; a new worktree row hangs straight down, no curve.
        let parent: Int?
        let choice: NewChatChoice
    }

    private static func addWorktrees(
        of name: String, at depth: Int, under parent: Int, map: BranchMap,
        to entries: inout [Entry], _ seen: inout Set<String>
    ) {
        for child in map.children(of: name) where child.worktree != nil {
            add(child, at: depth, under: parent, map: map, to: &entries, &seen)
        }
    }

    private static func add(
        _ branch: BranchMap.Branch, at depth: Int, under parent: Int?, map: BranchMap,
        to entries: inout [Entry], _ seen: inout Set<String>
    ) {
        guard seen.insert(branch.name).inserted else { return }
        entries.append(
            Entry(
                kind: .worktree, branch: branch.name, depth: depth, parent: parent,
                choice: branch.newChatChoice))
        let index = entries.count - 1
        addWorktrees(of: branch.name, at: depth + 1, under: index, map: map, to: &entries, &seen)
    }

    /// Each lane runs from its node down to its last child: through the rows between, and
    /// into a straight child's middle; a worktree's curve starts at its row's top.
    private static func rows(_ entries: [Entry]) -> [PlacePickerRow] {
        var lines = Array(repeating: [PlacePickerLine](), count: entries.count)
        for (index, entry) in entries.enumerated() {
            guard let last = entries.indices.last(where: { entries[$0].parent == index })
            else { continue }
            func line(_ fromTop: Bool, _ toBottom: Bool) -> PlacePickerLine {
                PlacePickerLine(
                    depth: entry.depth, lane: entry.branch, fromTop: fromTop, toBottom: toBottom)
            }
            lines[index].append(line(false, true))
            for between in (index + 1)..<last {
                lines[between].append(line(true, true))
            }
            if entries[last].kind == .newWorktree {
                lines[last].append(line(true, false))
            }
        }
        return entries.enumerated().map { index, entry in
            PlacePickerRow(
                kind: entry.kind, branch: entry.branch, depth: entry.depth,
                lines: lines[index].sorted { $0.depth < $1.depth },
                parentDepth: entry.kind == .worktree
                    ? entry.parent.map { entries[$0].depth } : nil,
                choice: entry.choice)
        }
    }
}

extension BranchMap.Branch {
    /// Where a click on its branch map row starts a chat (A8): the folder's branch in
    /// place, a worktree in its folder, any other branch on that branch itself.
    public var newChatChoice: NewChatChoice {
        if here {
            return .inPlace
        }
        if let worktree {
            return .worktree(path: worktree.path, branch: name)
        }
        return .onBranch(name)
    }
}
