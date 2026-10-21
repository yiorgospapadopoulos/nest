import NestKit
import SwiftUI

/// The project's branches and worktrees as coloured lanes (B96, A7), open under the
/// project header: each branch in its lane colour, joined to the branch it comes from by a
/// short curve; where the project folder is pulses. A click on a row starts a new chat
/// there (A8). At most six rows show; the rest scroll.
struct BranchMapPanel: View {
    static let visibleRows = 6
    let project: String
    let lanes: BranchLanes
    /// Snapshots only: the row drawn as hovered.
    var hovered: String?
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let chats = shell.branchMaps.chats(
            in: project, sessions: shell.sessions.sessions(in: project),
            claudeChats: shell.claudeChats.chats(in: project), repo: shell.repo,
            tone: shell.tone(of:))
        VStack(spacing: 0) {
            header
            Divider().overlay(Palette.divider)
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(lanes.rows) { row in
                        BranchMapRow(
                            project: project, row: row, width: lanes.width,
                            status: chats[row.id], showsHover: hovered == row.id
                        )
                        .transition(
                            reduceMotion
                                ? .opacity
                                : .asymmetric(
                                    insertion: .opacity.combined(with: .offset(x: -10)),
                                    removal: .opacity.combined(with: .offset(x: 10))))
                    }
                }
                .padding(.vertical, 2)
            }
            .scrollIndicators(.automatic)
            .frame(
                height: Double(min(lanes.rows.count, Self.visibleRows)) * BranchLaneRow.height
                    + 4)
        }
        .background(Palette.composer, in: .rounded(8))
        .animation(reduceMotion ? nil : .easeOut(duration: 0.5), value: lanes)
        .padding(EdgeInsets(top: 6, leading: 8, bottom: 2, trailing: 8))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Branch map")
    }

    @ViewBuilder private var header: some View {
        HStack(spacing: 6) {
            Text("Branches and worktrees")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            Spacer(minLength: 0)
            Text(lanes.count)
                .font(.ui(TypeSize.micro))
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .padding(.horizontal, 8)
        .frame(height: 28)
    }
}

/// One branch: its lanes, name, label and its chat's dot; hovered, a "New chat" chip in
/// the dot's place. A click starts a new chat there (A8).
private struct BranchMapRow: View {
    let project: String
    let row: BranchLaneRow
    let width: Double
    let status: BranchChatStatus?
    let showsHover: Bool
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        let branch = row.branch
        let hovered = hovering || showsHover
        Button {
            shell.newChat(at: branch.newChatChoice)
        } label: {
            HStack(spacing: 6) {
                LaneGraph(project: project, row: row, width: width)
                Text(branch.name)
                    .font(.ui(TypeSize.ui, branch.here ? .semibold : .regular))
                    .foregroundStyle(branch.here ? Palette.t1 : Palette.sidebarTextOpen)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .layoutPriority(1)
                if let label = row.label {
                    Text(label)
                        .font(.ui(TypeSize.micro))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                if hovered {
                    NewChatChip()
                } else if let status {
                    ChatDot(status: status)
                }
            }
            .padding(.trailing, hovered ? 6 : 10)
            .frame(height: BranchLaneRow.height)
            .background(hovered ? Palette.hover : .clear, in: .rounded(6))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .help(row.newChatHelp)
        .accessibilityLabel(row.accessibilityLabel(status: status))
    }
}

/// The hovered row's "+ New chat", in the selection's tint.
private struct NewChatChip: View {
    @Environment(\.accentColors) private var accent

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: Icon.plus).font(.system(size: 8, weight: .semibold))
            Text("New chat").font(.ui(TypeSize.micro)).lineLimit(1)
        }
        .foregroundStyle(Palette.t1)
        .padding(.horizontal, 6)
        .frame(height: 20)
        .background(accent.selection, in: .rounded(5))
        .fixedSize()
        .accessibilityHidden(true)
    }
}

/// A row's slice of the graph: the lines passing through, the curve from the parent's
/// lane and the node, pulsing where the project folder is.
private struct LaneGraph: View {
    let project: String
    let row: BranchLaneRow
    let width: Double
    @Environment(Shell.self) private var shell

    var body: some View {
        let height = BranchLaneRow.height
        let mid = height / 2
        let x = BranchLaneRow.x(row.depth)
        let own = color(row.branch.name)
        ZStack(alignment: .topLeading) {
            ForEach(row.lines, id: \.self) { line in
                let lineX = BranchLaneRow.x(line.depth)
                Path { path in
                    path.move(to: CGPoint(x: lineX, y: line.fromMiddle ? mid : 0))
                    path.addLine(to: CGPoint(x: lineX, y: height))
                }
                .stroke(color(line.lane), style: StrokeStyle(lineWidth: 2, lineCap: .round))
            }
            if let parent = row.parentDepth {
                let parentX = BranchLaneRow.x(parent)
                Path { path in
                    path.move(to: CGPoint(x: parentX, y: 0))
                    path.addCurve(
                        to: CGPoint(x: x, y: mid), control1: CGPoint(x: parentX, y: 12),
                        control2: CGPoint(x: x, y: 8))
                }
                .stroke(own, style: StrokeStyle(lineWidth: 2, lineCap: .round))
            }
            let radius = row.branch.here ? 5.0 : 4.0
            if row.branch.here {
                Pulse(color: own).position(x: x, y: mid)
            }
            Circle().fill(own)
                .frame(width: radius * 2, height: radius * 2)
                .position(x: x, y: mid)
        }
        .frame(width: width, height: height)
        .accessibilityHidden(true)
    }

    private func color(_ branch: String) -> Color {
        shell.branchMaps.color(of: branch, in: project).map(Color.init) ?? Palette.t3
    }
}

/// The ring that grows and fades around the here node; still with Reduce Motion.
private struct Pulse: View {
    let color: Color
    @Environment(\.reducedMotion) private var reduceMotion
    @State private var grown = false

    var body: some View {
        Circle()
            .stroke(color, lineWidth: 1.4)
            .frame(width: 9, height: 9)
            .scaleEffect(grown ? 2.6 : 1)
            .opacity(reduceMotion ? 0 : grown ? 0 : 0.7)
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.easeOut(duration: 2).repeatForever(autoreverses: false)) {
                    grown = true
                }
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

/// The header's mark that the map follows changes as they happen: shown while the event
/// stream is connected.
struct LiveMark: View {
    @Environment(\.reducedMotion) private var reduceMotion
    @State private var dim = false

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
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.easeInOut(duration: 0.8).repeatForever()) { dim = true }
        }
        .help("The branch map updates as branches and worktrees change")
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Live")
    }

    private var dot: some View {
        Circle().fill(StatusTone.review.color)
            .frame(width: 6, height: 6)
            .opacity(dim ? 0.35 : 1)
    }
}
