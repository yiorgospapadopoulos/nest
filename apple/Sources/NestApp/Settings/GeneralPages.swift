import AppKit
import NestKit
import SwiftUI

// MARK: General

struct GeneralPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let show = shell.settings.showAutomatedChats
        SettingsSection(title: "Sidebar") {
            SettingsRow(label: "Show automated chats") {
                Switch(isOn: show) { shell.setShowAutomatedChats(!show) }
                    .accessibilityLabel("Show automated chats")
            }
        }
        SettingsSection(title: "Nest") {
            SettingsRow(label: "Version") { SettingsValue(text: Self.version) }
            RestartRow()
        }
    }

    /// The bundle's version, or a build run from the checkout.
    static var version: String {
        guard Bundle.main.bundleURL.pathExtension == "app",
            let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
        else { return "Development build" }
        return version
    }
}

// MARK: Storage

/// Settings > Storage (B86): the space used, archiving, clean up and the search index.
struct StoragePage: View {
    @Environment(Shell.self) private var shell
    @State private var deleting: LargeAttachment?

    var body: some View {
        let storage = shell.model.storage
        SettingsSection(title: "", bare: true) {
            if let usage = storage.usage {
                StorageLedger(usage: usage)
            } else {
                SettingsRow(label: "Space used") { SettingsValue(text: "-") }
            }
            SettingsRow(label: "Archive chats idle for") {
                let days = storage.settings?.archiveAfterDays
                DropdownMenu(title: StorageText.archiveLabel(days), width: 110) {
                    ForEach(StorageText.archiveChoices, id: \.self) { choice in
                        Button(StorageText.archiveLabel(choice)) {
                            shell.settingsChange("Could not change archiving") {
                                try await storage.setArchiveAfterDays(choice)
                            }
                        }
                    }
                }
                .disabled(storage.settings == nil)
            }
            SettingsRow(label: "Clean up") {
                if storage.attachments == nil {
                    Button("Review large attachments…") {
                        shell.settingsChange("Could not list the attachments") {
                            try await storage.loadAttachments()
                        }
                    }
                    .buttonStyle(.nest(.soft))
                } else {
                    Button("Done") { storage.closeAttachments() }.buttonStyle(.nest(.soft))
                }
            }
            if let attachments = storage.attachments {
                AttachmentList(attachments: attachments) { deleting = $0 }
            }
            SettingsRow(label: "Search index") {
                if storage.isRebuilding {
                    Fireflies()
                }
                Button("Rebuild") {
                    shell.settingsChange("Could not rebuild the search index") {
                        try await storage.rebuildSearch()
                        shell.show("Rebuilding the search index", kind: .done)
                    }
                }
                .buttonStyle(.nest(.soft))
                .disabled(storage.isRebuilding)
            }
        }
        .task { try? await storage.load() }
        .confirmationDialog(
            "Delete \(deleting?.name ?? "this attachment")?", isPresented: deleteBinding,
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let attachment = deleting {
                    shell.settingsChange("Could not delete \(attachment.name)") {
                        try await storage.delete(attachment)
                    }
                }
                deleting = nil
            }
            Button("Cancel", role: .cancel) { deleting = nil }
        } message: {
            Text("It is deleted for good. Its chat shows that it is gone.")
        }
    }

    private var deleteBinding: Binding<Bool> {
        Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } })
    }
}

/// The space used (B86): the total, a bar of the parts, and one line per part with its
/// size and share.
private struct StorageLedger: View {
    let usage: StorageUsage

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(StorageText.bytes(usage.totalBytes))
                    .font(.ui(21, .semibold))
                    .monospacedDigit()
                Text("used by Nest")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
            }
            .accessibilityElement(children: .combine)
            StorageBar(usage: usage)
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                ForEach(StorageText.ledger(usage), id: \.part) { part, size, share in
                    GridRow {
                        Circle().fill(part.color).frame(width: 8, height: 8)
                        Text(part.name).frame(maxWidth: .infinity, alignment: .leading)
                        Text(size).gridColumnAlignment(.trailing)
                        Text(share)
                            .foregroundStyle(Palette.t3)
                            .frame(minWidth: 28, alignment: .trailing)
                            .gridColumnAlignment(.trailing)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .font(.ui(TypeSize.ui))
            .monospacedDigit()
        }
        .padding(.vertical, 12)
        .overlay(alignment: .bottom) { Separator() }
    }
}

/// The parts side by side across the width, 2 points apart, tiny ones kept visible.
private struct StorageBar: View {
    let usage: StorageUsage

    var body: some View {
        GeometryReader { geometry in
            let segments = StorageText.segments(
                StorageText.shares(usage), width: geometry.size.width, gap: 2, minimum: 3)
            HStack(spacing: 2) {
                ForEach(segments, id: \.part) { part, width in
                    RoundedRectangle(cornerRadius: 2).fill(part.color).frame(width: width)
                }
            }
        }
        .frame(height: 6)
        .accessibilityHidden(true)
    }
}

extension StorageText.Part {
    fileprivate var color: Color {
        switch self {
        case .chats: StatusTone.running.color
        case .attachments: StatusTone.waiting.color
        case .artifacts: StatusTone.review.color
        case .other: Palette.raised
        }
    }
}

/// The largest attachments, each with Delete.
private struct AttachmentList: View {
    let attachments: [LargeAttachment]
    let delete: (LargeAttachment) -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if attachments.isEmpty {
                Text("No attachments")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
                    .padding(.vertical, 8)
            }
            ForEach(attachments) { attachment in
                SettingsListRow(
                    title: attachment.name,
                    detail:
                        "\(StorageText.bytes(attachment.bytes)) · \(StorageText.source(of: attachment))"
                ) {
                    SettingsBadge(symbol: attachment.mediaType.hasPrefix("image") ? "photo" : "doc")
                } trailing: {
                    Button("Delete") { delete(attachment) }
                        .buttonStyle(.nest(.danger))
                        .disabled(shell.model.storage.deleting.contains(attachment.id))
                }
            }
        }
        .padding(.leading, 12)
    }
}

/// Restart Nest (B60): after a confirmation, restarts the Nest service, then quits and
/// reopens the app. When the service cannot restart, the app stays open and says why.
/// On a remote daemon (B105) it asks the daemon to restart, as the PWA does, and the app
/// stays open and reconnects.
private struct RestartRow: View {
    @Environment(AppController.self) private var controller
    @Environment(Shell.self) private var shell
    @State private var confirming = false
    @State private var restarting = false
    @State private var failure: String?

    var body: some View {
        SettingsRow(label: "Restart Nest") {
            if restarting {
                Fireflies()
            }
            Button("Restart") { confirming = true }
                .buttonStyle(.nest(.soft))
                .disabled(restarting)
        }
        .alert("Restart Nest?", isPresented: $confirming) {
            Button("Restart") { restart() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Running turns are interrupted and can be resumed afterwards.")
        }
        if let failure {
            SettingsFailure(text: failure)
        }
    }

    private func restart() {
        restarting = true
        failure = nil
        if shell.isRemote {
            restartRemote()
            return
        }
        Task {
            let result = await AppRestarter.local(service: controller.service).restart()
            switch result {
            case .relaunching:
                NSApp.terminate(nil)
            case .failed(let reason):
                failure = reason
                restarting = false
            }
        }
    }

    private func restartRemote() {
        let shell = self.shell
        Task {
            do {
                try await shell.model.restartDaemon()
                shell.show("Restarting Nest on \(shell.machineName)", kind: .done)
            } catch {
                failure = "Could not restart Nest on \(shell.machineName): \(Shell.describe(error))"
            }
            restarting = false
        }
    }
}

// MARK: Appearance

struct AppearancePage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let settings = shell.settings
        SettingsSection(title: "") {
            SettingsRow(label: "Mode") {
                Segmented(
                    options: [(ThemeMode.auto, "Auto"), (.light, "Light"), (.dark, "Dark")],
                    selection: settings.theme
                ) { settings.theme = $0 }
            }
            SettingsRow(label: "Accent colour") {
                HStack(spacing: 4) {
                    ForEach(AccentName.allCases, id: \.self) { name in
                        AccentSwatch(name: name, selected: settings.accent == name) {
                            settings.accent = name
                        }
                    }
                }
            }
        }
        AccentPreview()
        ChatBackgroundSection()
    }
}

/// B80's preview of the accent (a running row and a message bubble) goes here; it shows
/// nothing until then.
struct AccentPreview: View {
    var body: some View {
        EmptyView()
    }
}

/// The global chat background: an image behind the chat panes with its visibility while
/// no chat is open and once chats are open, and its grain. A project's own image is on its
/// Look tab.
private struct ChatBackgroundSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let background = shell.settings.chatBackground
        SettingsSection(title: "Chat background") {
            SettingsRow(label: "Image") {
                ImageButtons(hasImage: background.image != nil) {
                    shell.chooseChatBackground()
                } remove: {
                    shell.removeChatBackground()
                }
            }
            if let image = background.image {
                let global = background.background(for: nil) ?? ChatBackground(image: image)
                BackgroundPreview(background: global)
                BackgroundRows(background: global) { changed in
                    shell.settings.chatBackground.emptyVisibility = changed.emptyVisibility
                    shell.settings.chatBackground.chatsVisibility = changed.chatsVisibility
                    shell.settings.chatBackground.grain = changed.grain
                }
            }
        }
    }
}

/// Choose an image, or Change and Remove once there is one.
struct ImageButtons: View {
    let hasImage: Bool
    var removeTitle = "Remove"
    let choose: () -> Void
    let remove: () -> Void

    var body: some View {
        HStack(spacing: 6) {
            if hasImage {
                Button("Change", action: choose).buttonStyle(.nest(.soft))
                Button(removeTitle, action: remove).buttonStyle(.nest(.danger))
            } else {
                Button(action: choose) {
                    Label("Choose an image", systemImage: "photo.badge.plus")
                }
                .buttonStyle(.nest(.soft))
            }
        }
    }
}

/// The image as an empty workspace shows it, over the window's base color.
struct BackgroundPreview: View {
    let background: ChatBackground

    var body: some View {
        let shape = RoundedRectangle.rounded(Radius.card)
        let visibility = background.emptyVisibility
        Palette.windowOpaque
            .overlay {
                GrainedImage(path: background.image, grain: background.grain)
                    .opacity(visibility)
            }
            .overlay(alignment: .bottomLeading) {
                Text("Preview at \(Self.percent(visibility))")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .padding(8)
            }
            .frame(height: 110)
            .clipShape(shape)
            .overlay(shape.strokeBorder(Palette.divider))
            .padding(.vertical, 8)
            .overlay(alignment: .bottom) { Separator() }
            .accessibilityElement(children: .combine)
    }

    static func percent(_ value: Double) -> String {
        "\(Int((value * 100).rounded()))%"
    }
}

/// The visibility sliders and the grain: 0 percent the plain image, 100 MonoCode's full
/// dither.
struct BackgroundRows: View {
    let background: ChatBackground
    let change: (ChatBackground) -> Void

    var body: some View {
        let visibility = ChatBackground.minVisibility...ChatBackground.maxVisibility
        SettingsRow(label: "Visibility when empty") {
            PercentSlider(
                label: "Visibility when empty", value: background.emptyVisibility,
                range: visibility
            ) { value in update { $0.emptyVisibility = ChatBackground.clamp(value) } }
        }
        SettingsRow(label: "Visibility with chats") {
            PercentSlider(
                label: "Visibility with chats", value: background.chatsVisibility,
                range: visibility
            ) { value in update { $0.chatsVisibility = ChatBackground.clamp(value) } }
        }
        SettingsRow(label: "Grain") {
            PercentSlider(label: "Grain", value: background.grain, range: 0...1) { value in
                update { $0.grain = ChatBackground.clampGrain(value) }
            }
        }
    }

    private func update(_ apply: (inout ChatBackground) -> Void) {
        var next = background
        apply(&next)
        change(next)
    }
}

/// A slider in whole percent, with the value beside it.
private struct PercentSlider: View {
    let label: String
    let value: Double
    let range: ClosedRange<Double>
    let change: (Double) -> Void

    var body: some View {
        HStack(spacing: 8) {
            Slider(
                value: Binding(get: { value * 100 }, set: { change(($0).rounded() / 100) }),
                in: range.lowerBound * 100...range.upperBound * 100
            )
            .controlSize(.small)
            .tint(Palette.t2)
            .frame(width: 150)
            .accessibilityLabel(label)
            Text(BackgroundPreview.percent(value))
                .font(.ui(TypeSize.meta))
                .monospacedDigit()
                .foregroundStyle(Palette.t2)
                .frame(width: 34, alignment: .trailing)
        }
    }
}

private struct AccentSwatch: View {
    let name: AccentName
    let selected: Bool
    let pick: () -> Void

    var body: some View {
        let accent = Theme.accent(name)
        Button(action: pick) {
            Circle()
                .fill(Color(accent.fill))
                .overlay(Circle().strokeBorder(Palette.divider))
                .frame(width: 16, height: 16)
                .padding(3)
                .overlay {
                    if selected {
                        Circle().strokeBorder(Palette.t2, lineWidth: 1)
                    }
                }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(name.rawValue.capitalized)
        .accessibilityLabel(name.rawValue.capitalized)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// A small soft menu button: the value and a chevron.
struct DropdownMenu<Items: View>: View {
    let title: String
    var width: Double = 160
    @ViewBuilder let items: () -> Items
    @State private var hovering = false

    var body: some View {
        Menu {
            items()
        } label: {
            HStack(spacing: 8) {
                Text(title).font(.ui(TypeSize.button)).lineLimit(1)
                Spacer(minLength: 0)
                Image(systemName: Icon.chevron)
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(Palette.t2)
            }
            .foregroundStyle(Palette.t1)
            .padding(.leading, 9)
            .padding(.trailing, 8)
            .frame(width: width, height: Metrics.buttonHeight)
            .background(hovering ? Palette.selection : Palette.soft, in: .rounded(Radius.button))
            .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .menuIndicator(.hidden)
        .fixedSize()
        .onHover { hovering = $0 }
    }
}
