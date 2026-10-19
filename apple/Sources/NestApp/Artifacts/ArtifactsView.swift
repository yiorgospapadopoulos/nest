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
                Image(systemName: artifact.kind.symbol)
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

/// The selected version: its title, kind, where it came from and when (or that the user
/// edited it), the version stepper, Export PDF for slides and documents, Copy, Save as
/// file and Delete, then the document. The page's links ask "Open link?" here; moving to
/// another version or artifact, or closing, dismisses it.
private struct ArtifactReader: View {
    @Environment(Shell.self) private var shell
    @State private var confirmingDelete = false
    @State private var linkPrompt = ArtifactLinkPrompt()
    @State private var handle = ArtifactPageHandle()
    @State private var confirmingClear = false

    var body: some View {
        let store = shell.artifacts
        if let artifact = store.selected, let selection = store.selection {
            let content = store.selectedContent
            VStack(spacing: 0) {
                header(artifact, selection: selection, content: content)
                Separator()
                Group {
                    if let content, content.version == selection.version {
                        ArtifactDocument(content: content, prompt: linkPrompt, handle: handle)
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
            .confirmationDialog(
                "Open link?", isPresented: linkShown, titleVisibility: .visible,
                presenting: linkPrompt.request
            ) { request in
                Button("Open") { linkPrompt.answer(true, to: request.id) }
                Button("Cancel", role: .cancel) { linkPrompt.answer(false, to: request.id) }
            } message: { request in
                Text(request.message)
            }
            .confirmationDialog(
                "Clear this page\u{2019}s data?", isPresented: $confirmingClear,
                titleVisibility: .visible
            ) {
                Button("Clear page data", role: .destructive) { clearPageData(artifact.id) }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text(
                    "What the page stored is removed for every version and on every device. Open pages are told."
                )
            }
            .onChange(of: selection) { linkPrompt.dismiss() }
            .onDisappear { linkPrompt.dismiss() }
            .task(id: artifact.id) {
                try? await store.loadStorage(artifact.id)
                try? await store.loadAsks(artifact.id)
            }
            .onAppear {
                handle.reportSave = { [shell] result in
                    switch result {
                    case .success(let url):
                        shell.show("Saved \(url.lastPathComponent)", kind: .done)
                    case .failure(let error): shell.show(error, doing: "Could not save the file")
                    }
                }
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

    /// Shown while a link waits. A dismissal without a button declines it, after any
    /// button's own answer has run.
    private var linkShown: Binding<Bool> {
        Binding(
            get: { linkPrompt.request != nil },
            set: { shown in
                guard !shown, let id = linkPrompt.request?.id else { return }
                Task { @MainActor in linkPrompt.answer(false, to: id) }
            })
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
                    Text(
                        ArtifactText.line(
                            artifact, author: content?.author ?? .agent,
                            saved: content?.createdAt ?? artifact.updatedAt, now: context.date,
                            stored: store.storageSize(of: artifact.id),
                            asks: store.askCount(of: artifact.id))
                    )
                    .lineLimit(1)
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if store.isAsking(artifact.id) {
                HStack(spacing: 6) {
                    Fireflies(height: 10)
                    Text(ArtifactText.asking)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .fixedSize()
                }
                .accessibilityElement(children: .combine)
            }
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
            if let layout = ArtifactPrint.layout(artifact.kind) {
                Button {
                    exportPDF(content, layout: layout)
                } label: {
                    Label("Export PDF\u{2026}", systemImage: "doc.richtext")
                }
                .buttonStyle(.nest())
                .disabled(content?.version != selection.version)
                .help(ArtifactFile.pdfName(title: content?.title ?? artifact.title))
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
            if store.storageSize(of: artifact.id) > 0 {
                Button {
                    confirmingClear = true
                } label: {
                    Image(systemName: "eraser")
                }
                .buttonStyle(.nest(.plain, iconOnly: true))
                .help("Clear page data")
                .accessibilityLabel("Clear page data")
            }
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

    private func clearPageData(_ id: String) {
        Task {
            do {
                try await shell.artifacts.writeStorage(id, .clear)
            } catch {
                shell.show(error, doing: "Could not clear the page data")
            }
        }
    }

    private func exportPDF(_ content: ArtifactContent?, layout: ArtifactPrint) {
        guard let content else { return }
        handle.exportPDF(name: ArtifactFile.pdfName(title: content.title), layout: layout) {
            saved, url in
            if saved {
                shell.show("Saved \(url.lastPathComponent)", kind: .done)
            } else {
                shell.show("Could not export the PDF", kind: .failed)
            }
        }
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

/// A version's document: its page, HTML as saved or the page the daemon built for the
/// other kinds, in the sandboxed web view once its rule list is ready. A document's page
/// may save the user's edit, which moves the reader to the new version.
private struct ArtifactDocument: View {
    let content: ArtifactContent
    let prompt: ArtifactLinkPrompt
    let handle: ArtifactPageHandle
    @Environment(Shell.self) private var shell
    @State private var rules: WKContentRuleList?
    @State private var failure: String?

    var body: some View {
        Group {
            if let rules {
                ArtifactWebView(
                    page: content.page, artifactID: content.artifactID, rules: rules,
                    prompt: prompt, save: save, store: shell.artifacts, handle: handle)
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

extension ArtifactDocument {
    private var save: ArtifactBridgeSession.Save? {
        guard content.kind == .document else { return nil }
        let store = shell.artifacts
        let page = ArtifactSelection(id: content.artifactID, version: content.version)
        return { text, base in
            try await store.saveDocument(page, content: text, baseVersion: base)
        }
    }
}
