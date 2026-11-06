import NestKit
import SwiftUI

/// A row of the branch map (B96, B131), for the small map, the full tree and the Work on
/// picker: its lanes, its name, and what sits at its right, which `+ Worktree` replaces on
/// hover. A click selects, never more.
struct BranchRow: View {
    let project: String
    let row: BranchLaneRow
    var height = BranchLaneRow.height
    let selected: Bool
    let chat: BranchChatStatus?
    /// The picker's rows take their colour from the chat but draw no dot.
    var showsChat = true
    var behind: String?
    /// The new worktree button's word; nil on a row that has none.
    let addWord: String?
    /// A row of the full tree: its whole name, with nothing pushed to the right.
    var wide = false
    var mono = false
    /// What the row is called; the map's rows say it from the rest.
    var label: String?
    /// Snapshots only: the row drawn as hovered.
    var showsHover = false
    let pick: () -> Void
    let add: () -> Void
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        let hovered = hovering || showsHover
        let adds = hovered && addWord != nil
        let ink = color(row.lane(selected: selected, chat: chat))
        HStack(spacing: 0) {
            Button(action: pick) {
                HStack(spacing: 6) {
                    LaneGraph(project: project, row: row, height: height, ink: ink)
                    title
                    if let word = row.label {
                        Note(word)
                    }
                    if let remote = row.branch.remote {
                        Note(remote)
                    }
                    if !wide {
                        Spacer(minLength: 0)
                    }
                    if !adds {
                        if let behind {
                            Note(behind).monospacedDigit()
                        }
                        if showsChat, let chat {
                            ChatDot(status: chat)
                        }
                        if selected {
                            SelectedCheck(ink: ink)
                        }
                    }
                }
                .padding(.trailing, adds ? 6 : wide ? 12 : 10)
                .frame(height: height)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            // On a wide row the name takes its whole width before the filler has any.
            .layoutPriority(wide ? 1 : 0)
            if adds, let addWord {
                AddWorktreeChip(branch: row.branch.name, word: addWord, add: add)
                    .padding(.trailing, 8)
            }
            if wide {
                Color.clear
                    .frame(height: height)
                    .contentShape(Rectangle())
                    .onTapGesture(perform: pick)
            }
        }
        .background(
            selected ? ink.opacity(hovered ? 0.18 : 0.14) : hovered ? Palette.hover : .clear,
            in: .rounded(6)
        )
        .onHover { hovering = $0 }
        .help(row.branch.name)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(label ?? row.accessibilityLabel(status: chat))
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityAction(named: "New worktree from \(row.branch.name)") {
            if addWord != nil { add() }
        }
    }

    @ViewBuilder private var title: some View {
        let branch = row.branch
        let name = Text(branch.name)
            .font(
                mono ? .mono(TypeSize.meta) : .ui(TypeSize.ui, branch.here ? .semibold : .regular)
            )
            .foregroundStyle(branch.here ? Palette.t1 : Palette.sidebarTextOpen)
            .lineLimit(1)
            .truncationMode(.middle)
            .layoutPriority(1)
        if let parent = row.fromParent {
            VStack(alignment: .leading, spacing: 0) {
                name
                Text("from \(parent)")
                    .font(.ui(TypeSize.micro))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            .layoutPriority(1)
        } else {
            name
        }
    }

    private func color(_ branch: String) -> Color {
        shell.branchMaps.color(of: branch, in: project).map(Color.init) ?? Palette.t3
    }
}

extension BranchRow {
    /// A row of the small map or the full tree, which look the same.
    init(
        project: String, row: BranchLaneRow, selected: String?,
        chats: [String: BranchChatStatus], wide: Bool = false, showsHover: Bool = false,
        shell: Shell
    ) {
        let branch = row.branch
        self.init(
            project: project, row: row, selected: branch.name == selected, chat: chats[branch.name],
            behind: branch.behindNote, addWord: branch.remote == nil ? "Worktree" : nil, wide: wide,
            showsHover: showsHover
        ) {
            shell.select(branch, in: project)
        } add: {
            shell.newWorktree(from: branch.name)
        }
    }
}

/// Quiet words on a row.
private struct Note: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.micro))
            .foregroundStyle(Palette.t3)
            .lineLimit(1)
            .fixedSize()
    }
}

/// The new worktree button, which takes the row's right end on hover.
struct AddWorktreeChip: View {
    let branch: String
    let word: String
    let add: () -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        Button(action: add) {
            HStack(spacing: 3) {
                Image(systemName: Icon.plus).font(.system(size: 8, weight: .semibold))
                Text(word).font(.ui(TypeSize.micro)).lineLimit(1)
            }
            .foregroundStyle(Palette.t1)
            .padding(.horizontal, 6)
            .frame(height: 20)
            .background(accent.selection, in: .rounded(5))
            .contentShape(Rectangle())
            .fixedSize()
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityLabel("New worktree from \(branch)")
    }
}

/// The mark on the selected row, in the row's colour.
struct SelectedCheck: View {
    let ink: Color

    var body: some View {
        Image(systemName: Icon.check)
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(ink)
            .accessibilityHidden(true)
    }
}

/// A row's slice of the graph: the lines passing through, the curve from the parent's lane
/// and the node: filled for a worktree or where the project folder is, which pulses; hollow
/// for a plain branch; dotted for a branch only a remote has.
private struct LaneGraph: View {
    let project: String
    let row: BranchLaneRow
    let height: Double
    let ink: Color
    @Environment(Shell.self) private var shell

    var body: some View {
        let mid = height / 2
        let x = BranchLaneRow.x(row.depth)
        ZStack(alignment: .topLeading) {
            ForEach(row.lines, id: \.self) { line in
                let lineX = BranchLaneRow.x(line.depth)
                Path { path in
                    path.move(to: CGPoint(x: lineX, y: line.fromMiddle ? mid : 0))
                    path.addLine(to: CGPoint(x: lineX, y: height))
                }
                .stroke(lineColor(line.lane), style: Self.stroke)
            }
            if let parent = row.parentDepth {
                let parentX = BranchLaneRow.x(parent)
                Path { path in
                    path.move(to: CGPoint(x: parentX, y: 0))
                    if parent == row.depth {
                        path.addLine(to: CGPoint(x: x, y: mid))
                    } else {
                        path.addCurve(
                            to: CGPoint(x: x, y: mid), control1: CGPoint(x: parentX, y: mid - 5),
                            control2: CGPoint(x: x, y: mid - 9))
                    }
                }
                .stroke(ink, style: Self.stroke)
            }
            node.position(x: x, y: mid)
        }
        .frame(width: x + 14, height: height)
        .accessibilityHidden(true)
    }

    private static let stroke = StrokeStyle(lineWidth: 2, lineCap: .round)

    @ViewBuilder private var node: some View {
        let branch = row.branch
        if branch.remote != nil {
            Circle()
                .fill(Palette.side)
                .overlay(
                    Circle().stroke(ink, style: StrokeStyle(lineWidth: 1.6, dash: [1.8, 2]))
                )
                .frame(width: 6.8, height: 6.8)
        } else if branch.worktree != nil || branch.here {
            ZStack {
                if branch.here {
                    Pulse(color: ink)
                }
                let radius = branch.here ? 5.0 : 4.0
                Circle().fill(ink).frame(width: radius * 2, height: radius * 2)
            }
        } else {
            Circle()
                .fill(Palette.side)
                .overlay(Circle().stroke(ink, lineWidth: 1.8))
                .frame(width: 6.4, height: 6.4)
        }
    }

    private func lineColor(_ branch: String) -> Color {
        shell.branchMaps.color(of: branch, in: project).map(Color.init) ?? Palette.t3
    }
}

/// The project folder on a detached HEAD: where it is, with nothing to select. With `clear`,
/// a click goes back to the folder; it looks the same.
struct DetachedRow: View {
    let height: Double
    /// The top row's lane, when it runs on past this row.
    let trunk: Color?
    var clear: (() -> Void)?

    var body: some View {
        if let clear {
            Button(action: clear) { parts.contentShape(Rectangle()) }
                .buttonStyle(.plain)
                .accessibilityLabel("detached, here")
        } else {
            parts
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("detached, here")
        }
    }

    private var parts: some View {
        let mid = height / 2
        let x = BranchLaneRow.x(1)
        return HStack(spacing: 6) {
            ZStack(alignment: .topLeading) {
                if let trunk {
                    Path { path in
                        path.move(to: CGPoint(x: BranchLaneRow.x(0), y: 0))
                        path.addLine(to: CGPoint(x: BranchLaneRow.x(0), y: height))
                    }
                    .stroke(trunk, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                }
                ZStack {
                    Pulse(color: Palette.t3)
                    Circle().fill(Palette.t3).frame(width: 10, height: 10)
                }
                .position(x: x, y: mid)
            }
            .frame(width: x + 14, height: height)
            Text("detached")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.sidebarTextOpen)
            Note("here")
            Spacer(minLength: 0)
        }
        .frame(height: height)
    }
}

/// The ring that grows and fades around the here node; still with Reduce Motion.
private struct Pulse: View {
    let color: Color
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        if !reduceMotion {
            ColoredLayerMark<BranchPulseLayer>(color: color)
                .frame(width: BranchPulseLayer.side, height: BranchPulseLayer.side)
                .frame(width: 9, height: 9)
        }
    }
}

private final class BranchPulseLayer: ColoredMotionView {
    static let growth = 2.6
    /// Holds the ring at its largest, with its stroke.
    static let side = 28.0

    override func startMotion(in layer: CALayer) {
        guard let color else { return }
        // A border runs inside its layer, a SwiftUI stroke either side of the circle.
        let lineWidth = 1.4
        let ring = CALayer()
        ring.bounds = CGRect(x: 0, y: 0, width: 9 + lineWidth, height: 9 + lineWidth)
        ring.position = CGPoint(x: Self.side / 2, y: Self.side / 2)
        ring.cornerRadius = ring.bounds.width / 2
        ring.borderWidth = lineWidth
        ring.borderColor = color.cgColor
        ring.opacity = 0
        layer.sublayers = [ring]
        let grow = CABasicAnimation(keyPath: "transform.scale")
        grow.fromValue = 1
        grow.toValue = Self.growth
        let fade = CABasicAnimation(keyPath: "opacity")
        fade.fromValue = 0.7
        fade.toValue = 0
        for animation in [grow, fade] {
            animation.timingFunction = LayerLoop.easeOut
            LayerLoop.run(animation, period: 2, on: ring)
        }
    }
}

/// A branch's chat: running filled green, needing the user amber, idle an outline.
private struct ChatDot: View {
    let status: BranchChatStatus

    var body: some View {
        Group {
            switch status {
            case .running: Circle().fill(StatusTone.review.color)
            case .needsYou: Circle().fill(StatusTone.waiting.color)
            case .idle: Circle().strokeBorder(Palette.t3, lineWidth: 1)
            }
        }
        .frame(width: 6, height: 6)
        .accessibilityHidden(true)
    }
}
