import NestKit
import SwiftUI
import WebKit

/// The Artifacts view (B79): the history on the left, newest first, the focused chat's or
/// pixie's with a switch to the wider list, and the selected one in the reader.
struct ArtifactsView: View {
    static let listWidth = 290.0
    @Environment(Shell.self) private var shell
    @State private var failure: String?

    var body: some View {
        let store = shell.artifacts
        HStack(spacing: 0) {
            ArtifactList(failure: failure)
                .frame(width: Self.listWidth)
            Separator(axis: .vertical)
            ArtifactReader()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .onChange(of: shell.artifactScope, initial: true) { _, scope in
            if let scope {
                store.show(scope)
            }
        }
        .task(id: store.query) {
            do {
                try await store.open()
                failure = nil
            } catch {
                failure = "Could not load the artifacts: \(Shell.describe(error))"
            }
        }
    }
}

extension ArtifactKind {
    var icon: String { self == .html ? Icon.code : Icon.artifact }
}

/// The scope switch over the history rows.
private struct ArtifactList: View {
    let failure: String?
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.artifacts
        let items = store.query.flatMap(store.list)
        VStack(spacing: 0) {
            HStack(spacing: 2) {
                if let scope = store.scope, let narrow = scope.narrow {
                    ScopeButton(title: narrow.label, selected: !store.showsWide) {
                        setWide(false)
                    }
                    ScopeButton(title: scope.wide.label, selected: store.showsWide) {
                        setWide(true)
                    }
                } else {
                    SectionLabel(text: store.scope?.wide.label ?? "Artifacts")
                        .padding(.leading, 6)
                }
                Spacer(minLength: 0)
                if let items {
                    CountBadge(count: items.count)
                        .padding(.trailing, 6)
                }
            }
            .padding(.horizontal, 8)
            .frame(height: Metrics.headerHeight)
            ScrollView {
                LazyVStack(spacing: 2) {
                    if let failure {
                        Text(failure)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(StatusTone.failed.color)
                            .padding(12)
                    } else if let items, items.isEmpty, let query = store.query {
                        EmptyArtifacts(query: query)
                    }
                    ForEach(items ?? []) { artifact in
                        ArtifactRow(
                            artifact: artifact, selected: store.selection?.id == artifact.id)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 10)
            }
            .scrollIndicators(.never)
        }
        .frame(maxHeight: .infinity, alignment: .top)
    }

    private func setWide(_ wide: Bool) {
        Task {
            try? await shell.artifacts.setWide(wide)
        }
    }
}

private struct ScopeButton: View {
    let title: String
    let selected: Bool
    let action: () -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        Button(title, action: action)
            .buttonStyle(.plain)
            .font(.ui(TypeSize.meta, selected ? .medium : .regular))
            .foregroundStyle(selected ? Palette.t1 : Palette.t3)
            .padding(.horizontal, 8)
            .frame(height: 22)
            .background(selected ? accent.selection : .clear, in: .rounded(Radius.button))
            .contentShape(.rounded(Radius.button))
            .pointerStyle(.link)
            .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// Nothing saved in the scope: what shows here, and the wider list when it may have some.
private struct EmptyArtifacts: View {
    let query: ArtifactQuery
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.artifacts
        VStack(spacing: 8) {
            Text(ArtifactText.empty(query))
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .multilineTextAlignment(.center)
            Text("A chat saves a report, plan or page here when you ask it for one.")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .multilineTextAlignment(.center)
            if let wide = store.scope?.wide, store.scope?.narrow != nil, !store.showsWide {
                Button("Show \(wide.label.lowercased())") {
                    Task { try? await store.setWide(true) }
                }
                .buttonStyle(.nest())
                .padding(.top, 4)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 24)
        .frame(maxWidth: .infinity)
    }
}

/// An artifact in the history: its kind, title, the chat or pixie that made it and when;
/// a dot while its latest version is not opened yet.
private struct ArtifactRow: View {
    let artifact: Artifact
    let selected: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        Button {
            Task { try? await shell.artifacts.select(artifact.id) }
        } label: {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: artifact.kind.icon)
                    .font(.system(size: 11))
                    .foregroundStyle(Palette.t3)
                    .frame(width: 14)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 2) {
                    Text(artifact.title)
                        .font(.ui(TypeSize.ui, artifact.seen ? .regular : .medium))
                        .foregroundStyle(Palette.t1)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    TimelineView(.periodic(from: .now, by: 30)) { context in
                        Text(
                            "\(ArtifactText.origin(artifact)) · \(ArtifactText.when(artifact.updatedAt, now: context.date))"
                        )
                        .lineLimit(1)
                        .truncationMode(.middle)
                    }
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if !artifact.seen {
                    Circle()
                        .fill(accent.accent)
                        .frame(width: 6, height: 6)
                        .padding(.top, 5)
                        .accessibilityLabel("Not opened")
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 7)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRow(selected: selected)
        .pointerStyle(.link)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// The selected version: its title, kind, where it came from and when, the version
/// stepper, Copy, Save as file and Delete, then the document.
private struct ArtifactReader: View {
    @Environment(Shell.self) private var shell
    @State private var confirmingDelete = false

    var body: some View {
        let store = shell.artifacts
        if let artifact = store.selected, let selection = store.selection {
            let content = store.selectedContent
            VStack(spacing: 0) {
                header(artifact, selection: selection, content: content)
                Separator()
                Group {
                    if let content, content.version == selection.version {
                        ArtifactDocument(content: content)
                            .id(selection)
                    } else {
                        Fireflies(height: 14)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .confirmationDialog(
                "Delete \u{201C}\(artifact.title)\u{201D}?", isPresented: $confirmingDelete,
                titleVisibility: .visible
            ) {
                Button("Delete", role: .destructive) { shell.deleteArtifact(artifact.id) }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Every version is removed. Its cards in chats show it as deleted.")
            }
        } else {
            VStack(spacing: 8) {
                Image(systemName: Icon.artifact)
                    .font(.system(size: 20, weight: .light))
                    .foregroundStyle(Palette.t3)
                Text("Select an artifact to read it")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t2)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func header(
        _ artifact: Artifact, selection: ArtifactSelection, content: ArtifactContent?
    ) -> some View {
        let store = shell.artifacts
        return HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text(content?.title ?? artifact.title)
                    .font(.ui(TypeSize.reading, .semibold))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    let saved = content?.createdAt ?? artifact.updatedAt
                    Text(
                        "\(ArtifactText.kind(artifact.kind)) · \(ArtifactText.origin(artifact)) · saved \(ArtifactText.when(saved, now: context.date))"
                    )
                    .lineLimit(1)
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if artifact.latestVersion > 1 {
                HStack(spacing: 2) {
                    stepButton(-1, icon: Icon.chevronLeft, label: "Previous version")
                    Text(ArtifactText.version(selection.version, of: artifact.latestVersion))
                        .font(.ui(TypeSize.meta))
                        .monospacedDigit()
                        .foregroundStyle(Palette.t2)
                        .fixedSize()
                    stepButton(1, icon: Icon.chevronRight, label: "Next version")
                }
                .disabled(!store.canStep(by: -1) && !store.canStep(by: 1))
            }
            Button {
                if let content {
                    shell.copyText(content.content)
                }
            } label: {
                Label("Copy", systemImage: Icon.copy)
            }
            .buttonStyle(.nest())
            .disabled(content == nil)
            .help("Copy this version's text")
            Button {
                if let content {
                    shell.saveArtifact(content)
                }
            } label: {
                Label("Save as file", systemImage: "square.and.arrow.down")
            }
            .buttonStyle(.nest())
            .disabled(content == nil)
            .help(ArtifactFile.name(title: content?.title ?? artifact.title, kind: artifact.kind))
            Button {
                confirmingDelete = true
            } label: {
                Image(systemName: Icon.trash)
            }
            .buttonStyle(.nest(.plain, iconOnly: true))
            .help("Delete this artifact")
            .accessibilityLabel("Delete")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    private func stepButton(_ offset: Int, icon: String, label: String) -> some View {
        Button {
            Task { try? await shell.artifacts.step(by: offset) }
        } label: {
            Image(systemName: icon).font(.system(size: 9, weight: .semibold))
        }
        .buttonStyle(.nest(.plain, height: 22, iconOnly: true))
        .disabled(!shell.artifacts.canStep(by: offset))
        .help(label)
        .accessibilityLabel(label)
    }
}

/// A version's document: its page, HTML as saved or the daemon's rendering of the
/// Markdown, in the sandboxed web view once its rule list is ready.
private struct ArtifactDocument: View {
    let content: ArtifactContent
    @State private var rules: WKContentRuleList?
    @State private var failure: String?

    var body: some View {
        Group {
            if let rules {
                ArtifactWebView(page: content.page, rules: rules)
            } else if let failure {
                Text(failure)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(StatusTone.failed.color)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                Color.clear
            }
        }
        .task {
            do {
                rules = try await ArtifactSandbox.rules()
            } catch {
                failure = "This page cannot be shown safely: \(error.localizedDescription)"
            }
        }
    }
}
