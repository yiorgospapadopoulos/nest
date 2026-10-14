import NestKit
import SwiftUI

/// A file of the pixie's folder as plain text, inside the details panel. Saving names
/// the hash it read, so a change the pixie made meanwhile is never overwritten without
/// the user choosing to (D072).
struct PixieFilePage: View {
    let pixie: Pixie
    /// `soul`, `memory` or `notes/<name>`.
    let name: String
    let title: String
    /// Where the back button goes, such as "Details".
    let back: String
    let close: () -> Void
    @Environment(Shell.self) private var shell
    /// As read; nil while loading.
    @State private var file: LoadedFile?
    @State private var text = ""
    /// The file as it is now, after a save that named an old hash.
    @State private var stale: PixieFile?
    @State private var saving = false

    var body: some View {
        VStack(spacing: 0) {
            PanelPageHeader(title: title, back: back, close: close) {
                Button("Save") { save(hash: file?.hash) }
                    .buttonStyle(.nest(.primary))
                    .disabled(file == nil || saving)
                    .keyboardShortcut("s")
            }
            if let stale {
                StaleNote(pixie: pixie.name) {
                    file = LoadedFile(stale)
                    text = stale.text
                    self.stale = nil
                } keepMine: {
                    save(hash: stale.hash)
                }
                .padding(.horizontal, 12)
                .padding(.top, 10)
            }
            TextEditor(text: $text)
                .font(.mono(TypeSize.meta))
                .lineSpacing(4)
                .foregroundStyle(Palette.t1)
                .scrollContentBackground(.hidden)
                .scrollIndicators(.never)
                .disabled(file == nil)
                .padding(EdgeInsets(top: 10, leading: 10, bottom: 10, trailing: 10))
                .accessibilityLabel(title)
        }
        .task {
            guard let loaded = await LoadedFile.read(pixie.id, name, shell: shell) else {
                close()
                return
            }
            file = loaded
            text = loaded.text
        }
    }

    private func save(hash: String?) {
        stale = nil
        saving = true
        Task {
            defer { saving = false }
            do {
                _ = try await shell.pixies.save(pixie.id, name: name, text: text, hash: hash)
                shell.show("Saved \(title)", kind: .done)
                close()
            } catch APIError.staleFile(let current, let currentHash) {
                withAnimation { stale = PixieFile(text: current, hash: currentHash) }
            } catch {
                shell.show(error, doing: "Could not save \(title)")
            }
        }
    }
}

/// A pixie file as read: one that does not exist yet reads as empty, with no hash to name.
struct LoadedFile: Equatable {
    var text: String
    var hash: String?

    init(_ file: PixieFile) {
        text = file.text
        hash = file.hash
    }

    init(text: String, hash: String?) {
        self.text = text
        self.hash = hash
    }

    /// Nil when it could not be read; the failure shows as a toast.
    @MainActor
    static func read(_ id: String, _ name: String, shell: Shell) async -> LoadedFile? {
        do {
            return LoadedFile(try await shell.pixies.file(id, name: name))
        } catch APIError.notFound {
            return LoadedFile(text: "", hash: nil)
        } catch {
            shell.show(error, doing: "Could not read the file")
            return nil
        }
    }
}

/// The back button, the page's title and an action on the right.
struct PanelPageHeader<Trailing: View>: View {
    let title: String
    let back: String
    let close: () -> Void
    @ViewBuilder let trailing: () -> Trailing

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                Text(title)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                    .padding(.horizontal, 84)
                HStack(spacing: 0) {
                    Button(action: close) {
                        Label(back, systemImage: Icon.chevronLeft)
                    }
                    .buttonStyle(.nest(.plain))
                    .help("Back to \(back)")
                    Spacer(minLength: 8)
                    trailing()
                }
            }
            .padding(.horizontal, 8)
            .frame(height: Metrics.headerHeight)
            Separator()
        }
    }
}

/// The file changed after it was opened: load theirs, or save mine over it.
private struct StaleNote: View {
    let pixie: String
    let reload: () -> Void
    let keepMine: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            StatusLabel(tone: .waiting, label: "Changed meanwhile")
            Text("The file changed after you opened it, perhaps by \(pixie).")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t1)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                Button("Reload", action: reload)
                    .buttonStyle(.nest())
                Button("Keep mine", action: keepMine)
                    .buttonStyle(.nest(.primary))
            }
            .padding(.top, 2)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .softFill()
        .accessibilityElement(children: .contain)
    }
}
