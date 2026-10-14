import HarnessKit
import SwiftUI

/// What the pixie remembers: the facts of MEMORY.md, its notes and a search over both,
/// inside the details panel.
struct PixieMemoryPage: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell
    @State private var file: LoadedFile?
    @State private var fact = ""
    @State private var notes: [String]?
    @State private var query = ""
    @State private var hits: [PixieSearchHit]?

    var body: some View {
        VStack(spacing: 0) {
            PanelPageHeader(title: "Memory", back: "Details") {
                shell.pixiePanel = .details
            } trailing: {
                EmptyView()
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    DetailHeading(title: "Facts", divided: false)
                    if let file {
                        facts(in: file)
                        addField(file)
                            .padding(.horizontal, 8)
                            .padding(.top, 6)
                    }

                    DetailHeading(title: "Notes")
                    if let notes {
                        DetailGroup {
                            if notes.isEmpty {
                                DetailLine(text: "No notes yet", dim: true)
                            }
                            ForEach(notes, id: \.self) { note in
                                NoteRow(name: note) { shell.pixiePanel = .note(note) }
                            }
                        }
                    }

                    DetailHeading(title: "Search")
                    TextField("Search memory and notes", text: $query)
                        .textFieldStyle(.plain)
                        .font(.ui(TypeSize.ui))
                        .padding(.horizontal, 8)
                        .frame(height: 24)
                        .background(Palette.soft, in: .rounded(Radius.button))
                        .padding(.horizontal, 8)
                        .onSubmit(search)
                        .accessibilityLabel("Search memory")
                    if let hits {
                        DetailGroup {
                            if hits.isEmpty {
                                DetailLine(text: "No matches", dim: true)
                            }
                            ForEach(Array(hits.enumerated()), id: \.offset) { _, hit in
                                Text("\(hit.file): \(hit.line)")
                                    .font(.ui(TypeSize.ui))
                                    .foregroundStyle(Palette.t1)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .textSelection(.enabled)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 5)
                            }
                        }
                        .padding(.top, 6)
                    }
                }
                .padding(EdgeInsets(top: 0, leading: 6, bottom: 14, trailing: 6))
            }
            .scrollIndicators(.never)
        }
        .task {
            guard let read = await LoadedFile.read(pixie.id, "memory", shell: shell) else {
                shell.pixiePanel = .details
                return
            }
            file = read
            notes = (try? await shell.pixies.notes(pixie.id)) ?? []
        }
    }

    private func facts(in file: LoadedFile) -> some View {
        let facts = PixieMemory.facts(in: file.text)
        return DetailGroup {
            if facts.isEmpty {
                DetailLine(text: "No facts yet", dim: true)
            }
            ForEach(facts, id: \.id) { fact in
                HStack(alignment: .top, spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(fact.text)
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(Palette.t1)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                        if !fact.date.isEmpty {
                            Text(fact.date)
                                .font(.ui(TypeSize.meta))
                                .monospacedDigit()
                                .foregroundStyle(Palette.t3)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    RemoveButton(label: "Remove fact: \(fact.text)") {
                        write(PixieMemory.removing(line: fact.line, from: file.text), over: file)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
            }
        }
    }

    private func addField(_ file: LoadedFile) -> some View {
        HStack(spacing: 6) {
            TextField("Add fact", text: $fact)
                .textFieldStyle(.plain)
                .font(.ui(TypeSize.ui))
                .padding(.horizontal, 8)
                .frame(height: 24)
                .background(Palette.soft, in: .rounded(Radius.button))
                .onSubmit { add(to: file) }
                .accessibilityLabel("Add fact")
            Button("Add") { add(to: file) }
                .buttonStyle(.harness(.primary, height: 24))
                .disabled(fact.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
    }

    private func add(to file: LoadedFile) {
        let text = fact.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let day = PixieMemory.day(of: Date())
        write(PixieMemory.adding(text, to: file.text, on: day), over: file) { fact = "" }
    }

    /// Saves MEMORY.md on the hash it was read with. When the pixie wrote meanwhile, its
    /// version shows and the user does it again.
    private func write(
        _ text: String, over current: LoadedFile, then done: @escaping () -> Void = {}
    ) {
        Task {
            do {
                let saved = try await shell.pixies.save(
                    pixie.id, name: "memory", text: text, hash: current.hash)
                file = LoadedFile(saved)
                done()
            } catch APIError.staleFile(let theirs, let hash) {
                file = LoadedFile(text: theirs, hash: hash)
                shell.show("Memory changed meanwhile. Try again.", kind: .info)
            } catch {
                shell.show(error, doing: "Could not save the memory")
            }
        }
    }

    private func search() {
        let text = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        Task {
            do {
                hits = try await shell.pixies.search(pixie.id, query: text)
            } catch {
                shell.show(error, doing: "Could not search")
            }
        }
    }
}

/// A note, opening it as a file page.
private struct NoteRow: View {
    let name: String
    let open: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: open) {
            HStack(spacing: 8) {
                Image(systemName: Icon.file)
                    .font(.system(size: 10))
                    .foregroundStyle(Palette.t3)
                Text(name)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                Spacer(minLength: 4)
                Image(systemName: Icon.chevronRight)
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(Palette.t2)
            }
            .padding(.horizontal, 8)
            .frame(height: Metrics.rowHeight + 2)
            .background(hovering ? Palette.soft : .clear, in: .rounded(Radius.row))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .accessibilityLabel("Note \(name)")
    }
}
