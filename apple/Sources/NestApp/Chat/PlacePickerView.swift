import NestKit
import SwiftUI

/// The new chat's "Work on" button (B96, P1): where the chat works, a worktree's branch in
/// its lane colour; it opens the picker over the composer. `quiet` draws it as the start
/// screen's plain text, else as the pane composer's capsule. A long name is cut, at most
/// `maxWidth` and less when the pane is narrow, so it pushes nothing off screen.
struct WorkOnButton: View {
    static let maxWidth = 300.0
    @Bindable var draft: ComposerDraft
    let repo: Repo
    let picker: PlacePicker
    let quiet: Bool
    @Environment(Shell.self) private var shell
    @State private var open = false
    @State private var hovering = false

    var body: some View {
        let place = draft.place(in: repo)
        let title = NewChatPlace.title(place, repo: repo)
        let lane: Color? =
            if case .worktree(_, let branch) = place {
                shell.branchMaps.color(of: branch, in: repo.name).map(Color.init)
            } else {
                nil
            }
        Button {
            open.toggle()
        } label: {
            WidthCap(maxWidth: Self.maxWidth - 2 * padding) {
                HStack(spacing: quiet ? 4 : 5) {
                    if !quiet || lane != nil {
                        BranchIcon(size: 10)
                    }
                    Text(title)
                        .font(lane == nil ? .ui(TypeSize.button) : .mono(TypeSize.meta))
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Image(systemName: open ? Icon.chevronUp : Icon.chevron)
                        .font(.system(size: 8, weight: .semibold))
                        .opacity(quiet ? 1 : 0.5)
                }
            }
            .foregroundStyle(lane ?? (quiet ? (hovering ? Palette.t1 : Palette.t2) : text))
            .padding(.horizontal, padding)
            .frame(height: quiet ? Metrics.buttonHeight : 24)
            .background { background }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .fixedSize(horizontal: false, vertical: true)
        .onHover { hovering = $0 }
        .help("Where the chat works")
        .accessibilityLabel("Where the chat works: \(title)")
        .onChange(of: open) { _, open in
            if open {
                shell.readBranches(of: repo.name)
            }
        }
        .popover(isPresented: $open, arrowEdge: .top) {
            if let map = shell.branchMaps.map(repo.name) {
                PlacePickerList(repo: repo, map: map, picker: picker, selected: place) { choice in
                    draft.chosenPlace = choice
                    open = false
                }
            }
        }
    }

    private var padding: Double { quiet ? 6 : 10 }

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

/// The picker (P1, B131): Find, the top row pinned, every other branch in its lane with
/// "New worktree" on hover, scrolling past eight rows, then what only the remotes have.
struct PlacePickerList: View {
    static let width = 300.0
    /// Find and the full tree reach the others.
    static let remoteRows = 40
    let repo: Repo
    let map: BranchMap
    let picker: PlacePicker
    let selected: NewChatChoice
    /// Snapshots only: the row drawn as hovered.
    var hovered: String?
    let choose: (NewChatChoice) -> Void
    @Environment(Shell.self) private var shell
    @State private var query = ""

    var body: some View {
        let chats = shell.branchMaps.chats(
            in: repo.name, sessions: shell.sessions.sessions(in: repo.name),
            claudeChats: shell.claudeChats.chats(in: repo.name), repo: repo,
            tone: shell.tone(of:))
        VStack(alignment: .leading, spacing: 0) {
            FindField(placeholder: "Where this chat works", text: $query, size: TypeSize.ui)
                .padding(EdgeInsets(top: 3, leading: 8, bottom: 7, trailing: 8))
            if query.isEmpty {
                rows(chats: chats)
            } else {
                FoundRows(map: map, query: query, picks: picks, maxHeight: 330)
            }
        }
        .padding(EdgeInsets(top: 6, leading: 6, bottom: 6, trailing: 4))
        .frame(width: Self.width)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Where this chat works")
    }

    @ViewBuilder private func rows(chats: [String: BranchChatStatus]) -> some View {
        let lead = map.detached ? 1 : 0
        let target = picker.rows.first { selected.marks($0.branch, repo: repo) }
        if let top = picker.top {
            row(top, chats: chats)
        }
        RevealingRows(
            count: picker.rows.count + lead, rowHeight: PlacePickerRow.height,
            visible: PlacePicker.visibleRows,
            index: target.flatMap(picker.rows.firstIndex(of:)).map { $0 + lead }
        ) {
            if map.detached {
                DetachedRow(height: PlacePickerRow.height, trunk: trunk)
            }
            ForEach(picker.rows) { row($0, chats: chats) }
        }
        .padding(.trailing, 2)
        if !map.remoteBranches.isEmpty {
            Rectangle().fill(Palette.divider)
                .frame(height: 1)
                .padding(.horizontal, 6)
                .padding(.vertical, 4)
        }
        RemoteFold(
            remotes: map.remoteBranches.prefix(Self.remoteRows), count: map.remoteBranches.count,
            rule: false, tall: true, maxHeight: 120, pick: pickRemote)
    }

    private func row(_ row: PlacePickerRow, chats: [String: BranchChatStatus]) -> BranchRow {
        let marked = selected.marks(row.branch, repo: repo)
        return BranchRow(
            project: repo.name, row: row.lane, height: PlacePickerRow.height, selected: marked,
            chat: chats[row.id], showsChat: false,
            addWord: row.newWorktree == nil ? nil : "New worktree",
            mono: row.branch.worktree != nil,
            label: row.accessibilityLabel + (marked ? ", selected" : ""),
            showsHover: hovered == row.id
        ) {
            pick(row.branch)
        } add: {
            addWorktree(row.branch.name)
        }
    }

    /// The top row's lane, when it runs past the detached row.
    private var trunk: Color? {
        guard !picker.rows.isEmpty, let top = picker.top else { return nil }
        return shell.branchMaps.color(of: top.id, in: repo.name).map(Color.init)
    }

    private var picks: FoundPicks {
        FoundPicks(
            selected: { selected.marks($0, repo: repo) },
            color: { shell.branchMaps.color(of: $0, in: repo.name).map(Color.init) },
            pick: pick, pickRemote: pickRemote, add: addWorktree, addWord: "New worktree",
            tall: true)
    }

    private func pick(_ branch: BranchMap.Branch) {
        if let remote = branch.remote {
            pickRemote(BranchMap.RemoteBranch(remote: remote, name: branch.name))
        } else if !shell.branchMaps.picksHeld(repo.name) {
            choose(branch.newChatChoice)
        }
    }

    private func pickRemote(_ remote: BranchMap.RemoteBranch) {
        shell.track(remote, in: repo.name) { choose(.onBranch($0)) }
    }

    private func addWorktree(_ branch: String) {
        choose(.newWorktree(from: branch))
    }
}
