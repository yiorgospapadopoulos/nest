import AppKit
import NestKit
import SwiftUI

/// Everything in one sheet (B131): every level with no indent cap, worktrees and remotes,
/// scrolling both ways under the top row. A click selects as in the small map and the sheet
/// stays open with the mark moving.
struct BranchTreeSheet: View {
    static let width = 720.0
    static let height = 560.0
    static let headerHeight = 42.0
    let project: String
    @Environment(Shell.self) private var shell
    @State private var query = ""

    var body: some View {
        SheetFrame(
            title: "Branches and worktrees", width: Self.width, maxHeight: Self.height,
            scrolls: false
        ) {
            if let map = shell.branchMaps.map(project), let tree = shell.branchMaps.tree(project) {
                MapBar(project: project, query: $query, height: 32, leading: 16) { EmptyView() }
                if query.isEmpty {
                    BranchTreeRows(project: project, map: map, tree: tree)
                } else {
                    FoundRows(
                        map: map, query: query, picks: picks,
                        maxHeight: Self.height - Self.headerHeight - 32
                    )
                    .padding(.horizontal, 2)
                }
            }
        }
        .task { shell.readBranches(of: project) }
    }

    private var picks: FoundPicks {
        let selected = shell.repo?.selectedPlace?.branch
        return FoundPicks(
            selected: { $0.name == selected },
            color: { shell.branchMaps.color(of: $0, in: project).map(Color.init) },
            pick: { shell.select($0, in: project, reveals: true) },
            pickRemote: { shell.select($0, in: project) },
            add: shell.newWorktree(from:), addWord: "Worktree", tall: true)
    }
}

/// The top row, held outside the scroll box so it stays in view both ways and spans the
/// sheet, then every other row. The selected row and its name come into view on opening.
private struct BranchTreeRows: View {
    /// Each row's room past its name: its notes, marks and worktree button.
    static let rowExtras = 190.0
    /// A row's name after its lanes, past its node.
    static let nameInset = 20.0
    static let font = NSFont.systemFont(ofSize: TypeSize.ui, weight: .semibold)

    let project: String
    let map: BranchMap
    let tree: BranchLanes
    @Environment(Shell.self) private var shell
    @State private var position = ScrollPosition(x: 0, y: 0)
    @State private var offset = RowsOffset()
    @State private var viewport = CGSize.zero

    var body: some View {
        let chats = shell.branchMaps.chats(
            in: project, sessions: shell.sessions.sessions(in: project),
            claudeChats: shell.claudeChats.chats(in: project), repo: shell.repo,
            tone: shell.tone(of:))
        let selected = shell.repo?.selectedPlace?.branch
        let lead = map.detached ? 1 : 0
        let rowHeight = BranchLaneRow.height
        let remotes = map.remoteBranches
        let gap = remotes.isEmpty ? 0 : 13.0
        let total =
            Double(tree.rest.count + lead) * rowHeight + gap
            + Double(remotes.count) * FlatRow.tallHeight
        let width = contentWidth
        let index = tree.rest.firstIndex { $0.id == selected }
        VStack(spacing: 0) {
            if let top = tree.top {
                row(top, selected: selected, chats: chats)
                    .padding(.horizontal, 2)
                    .overlay(alignment: .bottom) { Divider().overlay(Palette.divider) }
            }
            ScrollView([.horizontal, .vertical]) {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if map.detached {
                        DetachedRow(
                            height: rowHeight, trunk: trunk,
                            clear: selected == nil ? nil : { shell.clearPlace(in: project) })
                    }
                    ForEach(tree.rest) { row($0, selected: selected, chats: chats) }
                    if !remotes.isEmpty {
                        Divider().overlay(Palette.divider)
                            .padding(.horizontal, 8)
                            .frame(height: gap)
                    }
                    ForEach(remotes) { branch in
                        RemoteRow(branch: branch, tall: true) {
                            shell.select(branch, in: project)
                        }
                    }
                }
                .frame(width: width, height: total, alignment: .topLeading)
            }
            .scrollPosition($position)
            .scrollIndicators(.automatic)
            .onScrollGeometryChange(for: CGPoint.self) {
                $0.contentOffset
            } action: { _, new in
                offset.x = new.x
                offset.y = new.y
            }
            .onScrollGeometryChange(for: CGSize.self) {
                $0.containerSize
            } action: { _, new in
                viewport = new
            }
            // A short list would sit in the middle of a taller box, away from the top row.
            .frame(maxHeight: total)
            .padding(.horizontal, 2)
            .task(
                id: RevealTrigger(
                    reveal: shell.mapReveals, hasRow: index != nil, measured: viewport != .zero)
            ) {
                guard viewport != .zero, let index else { return }
                reveal(tree.rest[index], at: index + lead, total: total, width: width)
            }
        }
    }

    private func reveal(_ lane: BranchLaneRow, at index: Int, total: Double, width: Double) {
        let y = RowReveal.offset(
            row: index, height: BranchLaneRow.height, current: offset.y,
            viewport: viewport.height, content: total)
        let start = BranchLaneRow.x(lane.depth) + Self.nameInset
        let x = RowReveal.sideways(
            start: start, end: start + nameWidth(lane.id), current: offset.x,
            viewport: viewport.width, content: width)
        if x != nil || y != nil {
            position.scrollTo(x: x ?? offset.x, y: y ?? offset.y)
        }
    }

    private func row(
        _ lane: BranchLaneRow, selected: String?, chats: [String: BranchChatStatus]
    ) -> BranchRow {
        BranchRow(
            project: project, row: lane, selected: selected, chats: chats, wide: true, shell: shell)
    }

    /// The top row's lane, when it runs past the detached row.
    private var trunk: Color? {
        guard !tree.rest.isEmpty, let top = tree.top else { return nil }
        return shell.branchMaps.color(of: top.id, in: project).map(Color.init)
    }

    private func nameWidth(_ name: String) -> Double {
        Double((name as NSString).size(withAttributes: [.font: Self.font]).width)
    }

    /// The widest row, as the list only lays out the rows on screen.
    private var contentWidth: Double {
        let branches = tree.rest.map {
            BranchLaneRow.x($0.depth) + Self.nameInset + nameWidth($0.id)
        }
        let remotes = map.remoteBranches.map { 34 + nameWidth($0.name) }
        return max(((branches + remotes).max() ?? 0) + Self.rowExtras, BranchTreeSheet.width - 4)
    }
}
