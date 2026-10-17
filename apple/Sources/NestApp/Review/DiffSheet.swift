import NestKit
import SwiftUI

/// A review's changes side by side (or unified), file by file, with Approve in the footer;
/// a review has no Reject (B56).
struct DiffSheet: View {
    enum Layout: Hashable {
        case split, unified
    }

    let approvalID: String
    @Environment(Shell.self) private var shell
    @State private var layout = Layout.split
    @State private var collapsed: Set<String> = []
    @State private var failure: String?

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
                            PublishTarget(
                                diff: diff,
                                pushes: PublishForm.pushes(
                                    for: session.flatMap(shell.sessions.session)))
                            if diff.files.isEmpty {
                                Text("No changes against the base.")
                                    .font(.ui(TypeSize.ui))
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
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(StatusTone.failed.color)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    Fireflies(height: 14).frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            if let approval {
                footer(approval)
            }
        }
        .foregroundStyle(Palette.t1)
        .frame(maxWidth: 1180, maxHeight: .infinity)
        .sheetSurface()
        // Read again on every opening, so it never shows an older review's changes.
        .task(id: approvalID) { await load(approval) }
    }

    private func header(_ approval: Approval?, _ diff: SessionDiff?) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Changes").font(.ui(TypeSize.body, .semibold))
                Text(approval?.title ?? "Already resolved")
                    .font(.ui(TypeSize.meta))
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
                Image(systemName: Icon.close).font(.system(size: 10, weight: .medium))
            }
            .buttonStyle(.nest(.plain, iconOnly: true))
            .accessibilityLabel("Close changes")
        }
        .padding(EdgeInsets(top: 9, leading: 18, bottom: 9, trailing: 10))
        .overlay(alignment: .bottom) { Separator() }
    }

    private func footer(_ approval: Approval) -> some View {
        let session = shell.sessions.session(approval.sessionID)
        return HStack(spacing: 6) {
            Spacer()
            Button {
                shell.show(.publish(approval.id))
            } label: {
                Label(
                    PublishForm.approveTitle(for: session),
                    systemImage: PublishForm.pushes(for: session) ? Icon.pullRequest : Icon.check)
            }
            .buttonStyle(.nest(.primary))
            .disabled(!shell.approvals.isReviewLoaded(approval))
        }
        .padding(EdgeInsets(top: 9, leading: 16, bottom: 10, trailing: 16))
        .overlay(alignment: .top) { Separator() }
    }

    private func load(_ approval: Approval?) async {
        guard let approval else { return }
        failure = nil
        do {
            try await shell.approvals.loadDiff(for: approval)
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

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button(action: toggle) {
                HStack(spacing: 8) {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .semibold))
                        .foregroundStyle(Palette.t3)
                        .rotationEffect(.degrees(collapsed ? -90 : 0))
                    Text(DiffRows.title(file))
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.link)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    if file.status != .modified {
                        Text(file.status.rawValue.capitalized)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                    }
                    Spacer()
                    if !file.binary {
                        HStack(spacing: 4) {
                            Text("+\(file.additions)").foregroundStyle(StatusTone.review.color)
                            Text("-\(file.deletions)").foregroundStyle(StatusTone.failed.color)
                        }
                        .font(.mono(TypeSize.meta))
                    }
                }
                .padding(.horizontal, 12)
                .frame(height: 30)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowHoverStyle(radius: 0))
            if !collapsed {
                Separator()
                if file.isNestedRepository {
                    note(FileDiff.nestedRepositoryNote)
                } else if file.binary {
                    note("Binary file, not shown")
                } else if file.hunks.isEmpty {
                    note("No line changes")
                }
                ForEach(Array(file.hunks.enumerated()), id: \.offset) { _, hunk in
                    Text(DiffRows.header(hunk))
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(1)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 3)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Palette.soft)
                    HunkText(hunk: hunk, layout: layout)
                }
                if file.truncated {
                    note("The rest of this file is too long to show here.")
                }
            }
        }
        .softFill()
        .clipShape(.rounded(Radius.card))
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(.ui(TypeSize.ui))
            .foregroundStyle(Palette.t3)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
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
                Separator(axis: .vertical)
                SelectableText(key: "n\(hunk.hashValue)") {
                    TextStyling.splitSide(rows.map(\.new))
                }
            }
            .padding(.vertical, 1)
        }
    }
}
