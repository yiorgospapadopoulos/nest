import NestKit
import SwiftUI

/// The new chat's "Work on" button (B96, P1): where the chat works, a worktree's branch in
/// its lane colour; it opens the picker over the composer. `quiet` draws it as the start
/// screen's plain text, else as the pane composer's capsule.
struct WorkOnButton: View {
    @Bindable var draft: ComposerDraft
    let repo: Repo
    let picker: PlacePicker
    let quiet: Bool
    @Environment(Shell.self) private var shell
    @State private var open = false
    @State private var hovering = false

    var body: some View {
        let title = NewChatPlace.title(draft.place, repo: repo)
        let lane: Color? =
            if case .worktree(_, let branch) = draft.place {
                shell.branchMaps.color(of: branch, in: repo.name).map(Color.init)
            } else {
                nil
            }
        Button {
            open.toggle()
        } label: {
            HStack(spacing: quiet ? 4 : 5) {
                if !quiet || lane != nil {
                    Image(systemName: Icon.branch).font(.system(size: 10, weight: .medium))
                }
                Text(title)
                    .font(lane == nil ? .ui(TypeSize.button) : .mono(TypeSize.meta))
                    .lineLimit(1)
                    .truncationMode(.middle)
                Image(systemName: open ? Icon.chevronUp : Icon.chevron)
                    .font(.system(size: 8, weight: .semibold))
                    .opacity(quiet ? 1 : 0.5)
            }
            .foregroundStyle(lane ?? (quiet ? (hovering ? Palette.t1 : Palette.t2) : text))
            .padding(.horizontal, quiet ? 6 : 10)
            .frame(height: quiet ? Metrics.buttonHeight : 24)
            .background { background }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .fixedSize()
        .onHover { hovering = $0 }
        .help("Where the chat works")
        .accessibilityLabel("Where the chat works: \(title)")
        .popover(isPresented: $open, arrowEdge: .top) {
            PlacePickerList(
                project: repo.name, picker: picker, selected: draft.place.resolved(repo)
            ) { choice in
                draft.place = choice
                open = false
            }
        }
    }

    private var text: Color { Ink.content(hovering ? 1 : 0.75) }

    @ViewBuilder private var background: some View {
        if quiet {
            RoundedRectangle(cornerRadius: Radius.button)
                .fill(hovering || open ? Palette.soft : .clear)
        } else {
            Capsule().fill(Ink.content(hovering || open ? 0.08 : 0.04))
                .overlay(Capsule().strokeBorder(Ink.content(0.1), lineWidth: 1))
        }
    }
}

/// The picker (P1): "Where this chat works", then a block per branch, divided, in a list
/// that scrolls once it reaches about eleven rows.
struct PlacePickerList: View {
    static let width = 300.0
    let project: String
    let picker: PlacePicker
    let selected: NewChatChoice
    let choose: (NewChatChoice) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Where this chat works")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(EdgeInsets(top: 4, leading: 8, bottom: 6, trailing: 8))
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(Array(picker.blocks.enumerated()), id: \.element.id) { index, block in
                        if index > 0 {
                            Rectangle().fill(Palette.divider)
                                .frame(height: 1)
                                .padding(.horizontal, 6)
                                .padding(.vertical, (PlacePicker.dividerHeight - 1) / 2)
                        }
                        ForEach(block.rows) { row in
                            PlacePickerRowView(
                                project: project, row: row, width: picker.width,
                                selected: row.choice == selected, choose: choose)
                        }
                    }
                }
                .padding(.trailing, 2)
            }
            .scrollIndicators(.automatic)
            .frame(height: picker.height)
        }
        .padding(EdgeInsets(top: 6, leading: 6, bottom: 6, trailing: 4))
        .frame(width: Self.width)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Where this chat works")
    }
}

/// One picker row: its slice of the lanes, its name and, selected, the tint and a check.
private struct PlacePickerRowView: View {
    let project: String
    let row: PlacePickerRow
    let width: Double
    let selected: Bool
    let choose: (NewChatChoice) -> Void
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        Button {
            choose(row.choice)
        } label: {
            content
                .background(
                    selected ? lane.opacity(0.14) : hovering ? Palette.hover : .clear,
                    in: .rounded(6)
                )
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .accessibilityLabel(row.accessibilityLabel + (selected ? ", selected" : ""))
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var lane: Color {
        shell.branchMaps.color(of: row.branch, in: project).map(Color.init) ?? Palette.t3
    }

    private var content: some View {
        HStack(spacing: 6) {
            PickerLaneGraph(project: project, row: row, width: width)
            Text(row.title)
                .font(font)
                .foregroundStyle(row.kind == .newWorktree ? Palette.t2 : Palette.t1)
                .lineLimit(1)
                .truncationMode(.middle)
                .layoutPriority(1)
            if let detail = row.detail {
                Text(detail)
                    .font(.ui(TypeSize.micro))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
                    .fixedSize()
            }
            Spacer(minLength: 0)
            if selected {
                Image(systemName: Icon.check)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(lane)
            }
        }
        .padding(.trailing, 10)
        .frame(height: PlacePickerRow.height)
    }

    private var font: Font {
        switch row.kind {
        case .folder: .ui(TypeSize.ui, .semibold)
        case .worktree: .mono(TypeSize.meta)
        case .branch, .newWorktree: .ui(TypeSize.ui)
        }
    }
}

/// A picker row's slice of the lanes, as the branch map draws them: the lines passing
/// through, the curve from the parent's lane into a worktree's node, the branch's node,
/// or the plus of a new worktree.
private struct PickerLaneGraph: View {
    let project: String
    let row: PlacePickerRow
    let width: Double
    @Environment(Shell.self) private var shell

    var body: some View {
        let height = PlacePickerRow.height
        let mid = height / 2
        let x = PlacePickerRow.x(row.depth)
        let own = color(row.branch)
        ZStack(alignment: .topLeading) {
            ForEach(row.lines, id: \.self) { line in
                let lineX = PlacePickerRow.x(line.depth)
                Path { path in
                    path.move(to: CGPoint(x: lineX, y: line.fromTop ? 0 : mid))
                    path.addLine(to: CGPoint(x: lineX, y: line.toBottom ? height : mid))
                }
                .stroke(color(line.lane), style: StrokeStyle(lineWidth: 2, lineCap: .round))
            }
            if let parent = row.parentDepth {
                let parentX = PlacePickerRow.x(parent)
                Path { path in
                    path.move(to: CGPoint(x: parentX, y: 0))
                    path.addCurve(
                        to: CGPoint(x: x, y: mid), control1: CGPoint(x: parentX, y: 10),
                        control2: CGPoint(x: x, y: 6))
                }
                .stroke(own, style: StrokeStyle(lineWidth: 2, lineCap: .round))
            }
            switch row.kind {
            case .newWorktree:
                Image(systemName: Icon.plus)
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(Palette.t2)
                    .position(x: PlacePickerRow.x(row.depth + 1), y: mid)
            case .folder, .branch, .worktree:
                let radius = row.kind == .worktree ? 3.5 : row.kind == .folder ? 4.5 : 4
                Circle().fill(own)
                    .frame(width: radius * 2, height: radius * 2)
                    .position(x: x, y: mid)
            }
        }
        .frame(width: width, height: height)
        .accessibilityHidden(true)
    }

    private func color(_ branch: String) -> Color {
        shell.branchMaps.color(of: branch, in: project).map(Color.init) ?? Palette.t3
    }
}
