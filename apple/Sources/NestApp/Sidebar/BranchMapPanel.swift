import AppKit
import NestKit
import SwiftUI

/// The project's branches and worktrees as coloured lanes (B96, B131), open under the
/// project header: the top row pinned, every other branch scrolling under the branch it came
/// from. A click selects where new chats start and nothing else; where the project folder is
/// pulses.
struct BranchMapPanel: View {
    /// Under the pinned top row; the rest scroll.
    static let visibleRows = 5
    /// Find and the full tree reach the others.
    static let remoteRows = 60
    let project: String
    let map: BranchMap
    let lanes: BranchLanes
    /// Snapshots only: the row drawn as hovered.
    var hovered: String?
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion
    @State private var query = ""

    var body: some View {
        let chats = shell.branchMaps.chats(
            in: project, sessions: shell.sessions.sessions(in: project),
            claudeChats: shell.claudeChats.chats(in: project), repo: shell.repo,
            tone: shell.tone(of:))
        let selected = shell.repo?.selectedPlace?.branch
        VStack(spacing: 0) {
            MapBar(project: project, query: $query) {
                MapBarButton(icon: Icon.maximize, label: "Full tree") {
                    shell.show(.branchTree(project))
                }
            }
            if query.isEmpty {
                rows(selected: selected, chats: chats)
            } else {
                FoundRows(
                    map: map, query: query, picks: picks(selected: selected), maxHeight: 204)
            }
        }
        .background(Palette.composer, in: .rounded(8))
        .clipShape(.rounded(8))
        .padding(EdgeInsets(top: 6, leading: 8, bottom: 2, trailing: 8))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Branch map")
    }

    @ViewBuilder private func rows(
        selected: String?, chats: [String: BranchChatStatus]
    ) -> some View {
        let lead = map.detached ? 1 : 0
        if let top = lanes.top {
            row(top, selected: selected, chats: chats)
        }
        RevealingRows(
            count: lanes.rest.count + lead, rowHeight: BranchLaneRow.height,
            visible: Self.visibleRows,
            index: lanes.rest.firstIndex { $0.id == selected }.map { $0 + lead },
            reveal: shell.mapReveals
        ) {
            if map.detached {
                DetachedRow(
                    height: BranchLaneRow.height, trunk: trunk,
                    clear: selected == nil ? nil : { shell.clearPlace(in: project) })
            }
            ForEach(lanes.rest) { lane in
                row(lane, selected: selected, chats: chats)
                    .transition(
                        reduceMotion
                            ? .opacity
                            : .asymmetric(
                                insertion: .opacity.combined(with: .offset(x: -10)),
                                removal: .opacity.combined(with: .offset(x: 10))))
            }
            .animation(motion, value: lanes)
        }
        // Only the rows and a short list's height animate: a scroll to a row while the list's
        // content grew would stop at the old end, with a strip of the row in view.
        .animation(motion, value: min(lanes.rest.count + lead, Self.visibleRows))
        RemoteFold(
            remotes: map.remoteBranches.prefix(Self.remoteRows), count: map.remoteBranches.count,
            rule: true, maxHeight: 130
        ) {
            shell.select($0, in: project)
        }
    }

    private func row(
        _ lane: BranchLaneRow, selected: String?, chats: [String: BranchChatStatus]
    ) -> BranchRow {
        BranchRow(
            project: project, row: lane, selected: selected, chats: chats,
            showsHover: hovered == lane.id, shell: shell)
    }

    private var motion: Animation? { reduceMotion ? nil : .easeOut(duration: 0.5) }

    /// The top row's lane, when it runs past the detached row.
    private var trunk: Color? {
        guard !lanes.rest.isEmpty, let top = lanes.top else { return nil }
        return shell.branchMaps.color(of: top.id, in: project).map(Color.init)
    }

    private func picks(selected: String?) -> FoundPicks {
        FoundPicks(
            selected: { $0.name == selected },
            color: { shell.branchMaps.color(of: $0, in: project).map(Color.init) },
            pick: {
                guard !shell.branchMaps.picksHeld(project) else { return }
                shell.select($0, in: project, reveals: true)
                query = ""
            },
            pickRemote: {
                guard !shell.branchMaps.picksHeld(project) else { return }
                shell.select($0, in: project)
                query = ""
            },
            add: shell.newWorktree(from:), addWord: "Worktree")
    }
}

/// A fixed-height list that brings its selected row into view: when it opens, and when
/// `reveal` goes up. A row already in view moves nothing, so reading the map again never
/// takes the list away from where the user scrolled to.
struct RevealingRows<Content: View>: View {
    let count: Int
    let rowHeight: Double
    let visible: Int
    let index: Int?
    var reveal = 0
    @ViewBuilder let content: () -> Content
    @State private var position = ScrollPosition(y: 0)
    @State private var offset = RowsOffset()

    var body: some View {
        let height = Double(min(count, visible)) * rowHeight
        let total = Double(count) * rowHeight
        ScrollView {
            LazyVStack(spacing: 0) { content() }
                .frame(height: total, alignment: .top)
        }
        .scrollPosition($position)
        .scrollIndicators(.automatic)
        .onScrollGeometryChange(for: Double.self) {
            $0.contentOffset.y
        } action: { _, new in
            offset.y = new
        }
        .frame(height: height)
        .task(id: RevealTrigger(reveal: reveal, hasRow: index != nil)) {
            // After the first layout, which sizes the content.
            await Task.yield()
            guard let index else { return }
            let target = RowReveal.offset(
                row: index, height: rowHeight, current: offset.y, viewport: height, content: total)
            if let target {
                position.scrollTo(y: target)
            }
        }
    }
}

/// What starts a list's reveal: asked for again, or the row turned up, as a new branch does
/// after its selection.
struct RevealTrigger: Equatable {
    let reveal: Int
    let hasRow: Bool
    var measured = true
}

/// Where a list has scrolled to, held apart so scrolling redraws nothing.
final class RowsOffset {
    var x = 0.0
    var y = 0.0
}

/// The header's mark that the map follows changes as they happen: shown while the event
/// stream is connected.
struct LiveMark: View {
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        // The word goes first when the header is short of room.
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 5) {
                dot
                Text("Live").fixedSize()
            }
            dot
        }
        .font(.ui(TypeSize.micro))
        .foregroundStyle(Palette.t3)
        .help("The branch map updates as branches and worktrees change")
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Live")
    }

    private var dot: some View {
        Group {
            if reduceMotion {
                Circle().fill(StatusTone.review.color)
            } else {
                ColoredLayerMark<LiveDotLayer>(color: StatusTone.review.color)
            }
        }
        .frame(width: 6, height: 6)
    }
}

private final class LiveDotLayer: ColoredMotionView {
    override func startMotion(in layer: CALayer) {
        guard let color else { return }
        layer.backgroundColor = color.cgColor
        layer.cornerRadius = 3
        let dim = CABasicAnimation(keyPath: "opacity")
        dim.fromValue = 1
        dim.toValue = 0.35
        dim.timingFunction = LayerLoop.easeInOut
        dim.autoreverses = true
        LayerLoop.run(dim, period: 0.8, on: layer)
    }
}
