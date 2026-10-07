import HarnessKit
import SwiftUI

/// A review's changes side by side (or unified), file by file, with Reject and Approve in
/// the footer.
struct DiffSheet: View {
    enum Layout: Hashable {
        case split, unified
    }

    let approvalID: String
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass
    @State private var layout = Layout.split
    @State private var collapsed: Set<String> = []
    @State private var failure: String?
    @State private var confirmingReject = false

    var body: some View {
        let approval = shell.approval(approvalID)
        let session = approval.map(\.sessionID)
        let diff = session.flatMap { shell.approvals.diffs[$0] }
        VStack(spacing: 0) {
            header(approval, diff)
            Group {
                if let diff {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 10) {
                            if diff.files.isEmpty {
                                Text("No changes against the base.")
                                    .font(.ui(TypeSize.small))
                                    .foregroundStyle(Palette.t3)
                                    .frame(maxWidth: .infinity)
                                    .padding(30)
                            }
                            ForEach(diff.files) { file in
                                FileSection(
                                    file: file, layout: layout,
                                    collapsed: collapsed.contains(file.path)
                                ) {
                                    withAnimation(.smooth(duration: 0.2)) {
                                        if collapsed.remove(file.path) == nil {
                                            collapsed.insert(file.path)
                                        }
                                    }
                                }
                            }
                        }
                        .padding(16)
                    }
                } else if let failure {
                    Text(failure)
                        .font(.ui(TypeSize.small))
                        .foregroundStyle(StatusTone.failed.textColor)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            if let approval {
                footer(approval)
            }
        }
        .foregroundStyle(Palette.t1)
        .frame(maxWidth: 1180, maxHeight: .infinity)
        .sheetGlass(radius: glass.sheetRadius)
        .shadow(color: glass.shadow, radius: 30, y: 18)
        .task(id: approvalID) { await load(session) }
    }

    private func header(_ approval: Approval?, _ diff: SessionDiff?) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Changes").font(.ui(TypeSize.headline, .bold))
                Text(approval?.title ?? "Already resolved")
                    .font(.ui(TypeSize.small))
                    .foregroundStyle(Palette.t3)
                    .lineLimit(1)
            }
            Spacer()
            if let stats = diff?.stats {
                DiffStat(additions: stats.additions, deletions: stats.deletions, files: stats.files)
            }
            Segmented(
                options: [(Layout.split, "Side by side"), (.unified, "Unified")], selection: layout
            ) { layout = $0 }
            Button {
                shell.close()
            } label: {
                Image(systemName: Icon.close).font(.system(size: 12, weight: .medium))
            }
            .buttonStyle(.harness(.ghost, iconOnly: true))
            .accessibilityLabel("Close changes")
        }
        .padding(EdgeInsets(top: 12, leading: 22, bottom: 12, trailing: 14))
        .overlay(alignment: .bottom) { Rectangle().fill(Palette.hair).frame(height: 1) }
    }

    private func footer(_ approval: Approval) -> some View {
        let session = shell.sessions.session(approval.sessionID)
        let violation = session?.gitViolation ?? false
        let acknowledged = shell.approvals.acknowledgedViolations.contains(approval.id)
        return HStack(spacing: 8) {
            if violation {
                ViolationNotice(approval: approval).frame(maxWidth: 420)
            }
            Spacer()
            if confirmingReject {
                Text("Close the chat and remove its worktree and branch?")
                    .font(.ui(TypeSize.small))
                    .foregroundStyle(Palette.t2)
                Button("Cancel") { confirmingReject = false }
                    .buttonStyle(.harness(.plain))
                Button("Reject") { shell.reject(approval) }
                    .buttonStyle(.harness(.destructive))
            } else {
                Button("Reject") { confirmingReject = true }
                    .buttonStyle(.harness(.danger))
                Button {
                    shell.show(.publish(approval.id))
                } label: {
                    Label(
                        session?.mode == .inPlace ? "Approve and commit" : "Approve and open PR",
                        systemImage: Icon.pullRequest)
                }
                .buttonStyle(.harness(.approve))
                .disabled(violation && !acknowledged)
            }
        }
        .padding(EdgeInsets(top: 10, leading: 16, bottom: 12, trailing: 16))
        .overlay(alignment: .top) { Rectangle().fill(Palette.hair).frame(height: 1) }
    }

    private func load(_ session: String?) async {
        guard let session, shell.approvals.diffs[session] == nil else { return }
        do {
            try await shell.approvals.loadDiff(session: session)
        } catch {
            failure = "Could not load the changes: \(Shell.describe(error))"
        }
    }
}

private struct FileSection: View {
    let file: FileDiff
    let layout: DiffSheet.Layout
    let collapsed: Bool
    let toggle: () -> Void
    @Environment(\.glass) private var glass

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button(action: toggle) {
                HStack(spacing: 8) {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(Palette.t3)
                        .rotationEffect(.degrees(collapsed ? -90 : 0))
                    Image(systemName: Icon.file).font(.system(size: 11)).foregroundStyle(Palette.t2)
                    Text(DiffRows.title(file))
                        .font(.mono(TypeSize.small, .semibold))
                        .lineLimit(1)
                        .truncationMode(.middle)
                    if file.status != .modified {
                        Text(file.status.rawValue.capitalized)
                            .font(.ui(TypeSize.micro, .bold))
                            .foregroundStyle(Palette.t2)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 1)
                            .background(Palette.fill2, in: Capsule())
                    }
                    Spacer()
                    if !file.binary {
                        HStack(spacing: 4) {
                            Text("+\(file.additions)").foregroundStyle(Palette.addedText)
                            Text("-\(file.deletions)").foregroundStyle(Palette.removedText)
                        }
                        .font(.mono(TypeSize.label, .semibold))
                    }
                }
                .padding(.horizontal, 12)
                .frame(height: 36)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle(radius: glass.radius.card))
            if !collapsed {
                Rectangle().fill(Palette.hair).frame(height: 1)
                if file.binary {
                    note("Binary file, not shown")
                } else if file.hunks.isEmpty {
                    note("No line changes")
                }
                ForEach(Array(file.hunks.enumerated()), id: \.offset) { _, hunk in
                    Text(DiffRows.header(hunk))
                        .font(.mono(TypeSize.caption))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 4)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Palette.fill)
                    HunkText(hunk: hunk, layout: layout)
                }
                if file.truncated {
                    note("The rest of this file is too long to show here.")
                }
            }
        }
        .background(glass.subtle, in: glass.rounded(glass.radius.card))
        .clipShape(glass.rounded(glass.radius.card))
        .overlay(glass.rounded(glass.radius.card).strokeBorder(Palette.hair))
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(.ui(TypeSize.small))
            .foregroundStyle(Palette.t3)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
    }
}

/// A hunk as selectable text: one text for unified, one per side for side by side.
private struct HunkText: View {
    let hunk: Hunk
    let layout: DiffSheet.Layout

    var body: some View {
        switch layout {
        case .unified:
            SelectableText(key: "u\(hunk.hashValue)") { TextStyling.unifiedHunk(hunk) }
                .padding(.vertical, 1)
        case .split:
            let rows = DiffRows.sideBySide(hunk)
            HStack(alignment: .top, spacing: 0) {
                SelectableText(key: "o\(hunk.hashValue)") {
                    TextStyling.splitSide(rows.map(\.old))
                }
                Rectangle().fill(Palette.hair).frame(width: 1)
                SelectableText(key: "n\(hunk.hashValue)") {
                    TextStyling.splitSide(rows.map(\.new))
                }
            }
            .padding(.vertical, 1)
        }
    }
}
