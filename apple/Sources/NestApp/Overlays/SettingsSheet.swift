import AppKit
import NestKit
import SwiftUI

/// Settings: appearance and the chat background, defaults for new chats, the usage
/// refresh, Claude Code chats, stuck chats, notifications, paired devices, the account,
/// its connectors and Restart Nest.
struct SettingsSheet: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let pairing = shell.model.devices.pairingCode != nil
        SheetFrame(title: "Settings", scrollTarget: pairing ? PairingCodeView.id : nil) {
            AppearanceSection()
            AgentDefaultsSection()
            UsageSection()
            ClaudeChatsSection()
            StuckSection()
            NotificationsSection()
            DevicesSection()
            AccountSection()
            SheetSection(title: "Connectors") { ConnectorsList(top: 4) }
            RestartSection()
        }
    }
}

/// Restart Nest (B60): after a confirmation, restarts the Nest service, then quits and
/// reopens the app. When the service cannot restart, the app stays open and says why.
private struct RestartSection: View {
    @Environment(AppController.self) private var controller
    @State private var confirming = false
    @State private var restarting = false
    @State private var failure: String?

    var body: some View {
        SheetSection(title: "Restart") {
            HStack(spacing: 12) {
                Text("Restarts the Nest service and reopens the app.")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                Spacer()
                if restarting {
                    Fireflies()
                }
                Button("Restart Nest") { confirming = true }
                    .buttonStyle(.nest(.soft))
                    .disabled(restarting)
            }
            .padding(.vertical, 6)
            if let failure {
                Text(failure)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(StatusTone.failed.color)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 6)
            }
        }
        .alert("Restart Nest?", isPresented: $confirming) {
            Button("Restart") { restart() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Running turns are interrupted and can be resumed afterwards.")
        }
    }

    private func restart() {
        restarting = true
        failure = nil
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
}

/// The Claude account the agents run on: name, plan and email.
struct AccountSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let agents = shell.agents
        SheetSection(title: "Account") {
            HStack(spacing: 12) {
                Avatar(name: shell.accountName, size: 32)
                VStack(alignment: .leading, spacing: 1) {
                    Text(shell.accountName).font(.ui(TypeSize.ui, .medium))
                    Text(agents.plan).font(.ui(TypeSize.meta)).foregroundStyle(Palette.t2)
                    if let email = agents.email {
                        Text(email)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .textSelection(.enabled)
                    }
                    Text("Signed in through Claude Code")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
            }
            .padding(.vertical, 6)
        }
    }
}

private struct AppearanceSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let settings = shell.settings
        SheetSection(title: "Appearance") {
            SheetRow(label: "Mode", first: true) {
                Segmented(
                    options: [(ThemeMode.auto, "Auto"), (.light, "Light"), (.dark, "Dark")],
                    selection: settings.theme
                ) { settings.theme = $0 }
            }
            SheetRow(label: "Accent") {
                HStack(spacing: 4) {
                    ForEach(AccentName.allCases, id: \.self) { name in
                        Swatch(name: name, selected: settings.accent == name) {
                            settings.accent = name
                        }
                    }
                }
            }
            ChatBackgroundRows()
        }
    }
}

/// The chat background, as MonoCode's: an image behind the chat panes with its
/// visibility while no chat is open and once chats are open, and the current project's
/// own image in place of it.
private struct ChatBackgroundRows: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let background = shell.settings.chatBackground
        SheetRow(label: "Background") {
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
        if let project = shell.project {
            let own = background.projects[project]
            SheetRow(label: "Background in \(project)") {
                HStack(spacing: 8) {
                    Text(own == nil ? "Follows the global background" : "Its own image")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                    ImageButtons(hasImage: own != nil, removeTitle: "Use global") {
                        shell.chooseChatBackground(for: project)
                    } remove: {
                        shell.removeChatBackground(for: project)
                    }
                }
            }
            if let own {
                BackgroundPreview(background: own)
                BackgroundRows(background: own) { changed in
                    shell.settings.chatBackground.projects[project] = changed
                }
            }
        }
        Text("An image behind your chat panes. It stays on this Mac.")
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .padding(.bottom, 4)
    }
}

/// Choose an image, or Change and Remove once there is one.
private struct ImageButtons: View {
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
private struct BackgroundPreview: View {
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
                Text("Empty preview at \(Self.percent(visibility))")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                    .padding(8)
            }
            .frame(height: 120)
            .clipShape(shape)
            .overlay(shape.strokeBorder(Palette.divider))
            .padding(.vertical, 6)
            .accessibilityElement(children: .combine)
    }

    static func percent(_ value: Double) -> String {
        "\(Int((value * 100).rounded()))%"
    }
}

/// The visibility sliders, "Empty" and "With chats", and the grain: 0 percent the plain
/// image, 100 MonoCode's full dither.
private struct BackgroundRows: View {
    let background: ChatBackground
    let change: (ChatBackground) -> Void

    var body: some View {
        let visibility = ChatBackground.minVisibility...ChatBackground.maxVisibility
        SheetRow(label: "Empty") {
            PercentSlider(
                label: "Empty background visibility", value: background.emptyVisibility,
                range: visibility
            ) { value in update { $0.emptyVisibility = ChatBackground.clamp(value) } }
        }
        SheetRow(label: "With chats") {
            PercentSlider(
                label: "Background visibility with chats", value: background.chatsVisibility,
                range: visibility
            ) { value in update { $0.chatsVisibility = ChatBackground.clamp(value) } }
        }
        SheetRow(label: "Grain") {
            PercentSlider(label: "Background grain", value: background.grain, range: 0...1) {
                value in update { $0.grain = ChatBackground.clampGrain(value) }
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
        HStack(spacing: 10) {
            Slider(
                value: Binding(get: { value * 100 }, set: { change(($0).rounded() / 100) }),
                in: range.lowerBound * 100...range.upperBound * 100
            )
            .controlSize(.small)
            .tint(Palette.t2)
            .frame(width: 160)
            .accessibilityLabel(label)
            Text(BackgroundPreview.percent(value))
                .font(.ui(TypeSize.meta))
                .monospacedDigit()
                .foregroundStyle(Palette.t2)
                .frame(width: 32, alignment: .trailing)
        }
    }
}

private struct Swatch: View {
    let name: AccentName
    let selected: Bool
    let pick: () -> Void

    var body: some View {
        let accent = Theme.accent(name)
        Button(action: pick) {
            Circle()
                .fill(Color(accent.fill))
                .overlay(Circle().strokeBorder(Palette.divider))
                .overlay {
                    if selected {
                        Image(systemName: Icon.check)
                            .font(.system(size: 8, weight: .bold))
                            .foregroundStyle(Color(accent.on))
                    }
                }
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

/// What new chats start with, kept on the daemon and shared with the iPhone.
struct AgentDefaultsSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let agents = shell.agents
        let defaults = agents.current
        SheetSection(title: "Agent defaults") {
            SheetRow(label: "Model", first: true) {
                DropdownMenu(title: agents.label(for: defaults.model)) {
                    ModelItems(current: defaults.model) { info in
                        change { try await agents.setDefaultModel(info.value) }
                    }
                }
            }
            SheetRow(label: "Thinking") {
                DropdownMenu(
                    title: defaults.effort?.label
                        ?? agents.defaultEffortLabel(for: defaults.model),
                    width: 260
                ) {
                    ThinkingItems(
                        model: defaults.model, effort: defaults.effort, offersDefault: true
                    ) { effort in
                        change { try await agents.setDefaultEffort(effort) }
                    }
                }
            }
            SheetRow(label: "Permission mode") {
                DropdownMenu(title: PermissionMode.label(defaults.permissionMode), width: 260) {
                    PermissionItems(
                        modes: agents.permissionModes(for: defaults.model),
                        current: defaults.permissionMode, offersDefault: true
                    ) { mode in change { try await agents.setDefaultPermissionMode(mode) } }
                }
            }
            SheetRow(label: "New chats work in") {
                Segmented(
                    options: [
                        (SessionMode.inPlace, "Work on current branch"),
                        (.worktree, "New worktree"),
                    ],
                    selection: defaults.mode
                ) { mode in change { try await agents.setDefaultMode(mode) } }
            }
            Text("Shared with Nest on your iPhone.")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.bottom, 4)
        }
    }

    private func change(_ action: @escaping () async throws -> Void) {
        Task {
            do {
                try await action()
            } catch {
                shell.show(error, doing: "Could not change the agent defaults")
            }
        }
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

/// How often the daemon asks Claude for the 5 hour and weekly limits (D031).
private struct UsageSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let usage = shell.model.usage
        SheetSection(title: "Usage") {
            SheetRow(label: "Refresh limits", first: true) {
                DropdownMenu(title: UsageText.refreshInterval(usage.refreshMinutes)) {
                    ForEach(UsageText.refreshChoices, id: \.self) { minutes in
                        Button(UsageText.refreshInterval(minutes)) { set(minutes) }
                    }
                }
                .disabled(usage.refreshMinutes == nil)
            }
            Text(
                "While Nest is on screen, a tiny check (about 400 tokens) keeps the 5 hour and weekly limits current. Refresh in the usage popover asks at once."
            )
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.bottom, 6)
        }
        .task { try? await usage.loadSettings() }
    }

    private func set(_ minutes: Int) {
        Task {
            do {
                try await shell.model.usage.setRefreshMinutes(minutes)
            } catch {
                shell.show(error, doing: "Could not change the usage refresh")
            }
        }
    }
}

/// Which Claude Code chats the sidebar lists.
private struct ClaudeChatsSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let show = shell.settings.showAutomatedChats
        SheetSection(title: "Claude Code chats") {
            SheetRow(label: "Show automated chats", first: true) {
                Switch(isOn: show) { shell.setShowAutomatedChats(!show) }
                    .accessibilityLabel("Show automated chats")
            }
            Text("Chats that scripts and scheduled tasks started in Claude Code.")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.bottom, 6)
        }
    }
}

/// When the daemon flags a running chat as stuck (D036).
struct StuckSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let settings = shell.model.stuck.settings
        SheetSection(title: "Stuck chats") {
            ForEach(Array(StuckThreshold.allCases.enumerated()), id: \.offset) { index, threshold in
                let value = settings?[keyPath: threshold.keyPath] ?? 0
                SheetRow(label: threshold.title, first: index == 0) {
                    DropdownMenu(title: settings == nil ? "…" : threshold.label(value)) {
                        ForEach(threshold.choices(including: value), id: \.self) { choice in
                            Button(threshold.label(choice)) {
                                shell.setStuckThreshold(threshold, to: choice)
                            }
                        }
                    }
                    .disabled(settings == nil)
                }
            }
            Text(
                "A running chat counts as stuck after any of these. Stuck chats show a badge and a card in Needs you with Send a nudge."
            )
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.bottom, 6)
        }
        .task { try? await shell.model.stuck.load() }
    }
}

struct NotificationsSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let settings = shell.settings
        let toggles = NotificationPreferences.toggles
        SheetSection(title: "Notifications") {
            ForEach(Array(toggles.enumerated()), id: \.offset) { index, toggle in
                SheetRow(label: toggle.title, first: index == 0) {
                    Switch(isOn: settings.notifications[keyPath: toggle.path]) {
                        settings.notifications[keyPath: toggle.path].toggle()
                    }
                    .accessibilityLabel(toggle.title)
                }
            }
        }
    }
}

/// Paired devices with Revoke, and pairing a new one with a one-time code.
private struct DevicesSection: View {
    @Environment(Shell.self) private var shell
    @State private var revoking: Device?

    var body: some View {
        let devices = shell.model.devices
        SheetSection(title: "Devices") {
            ForEach(Array(devices.devices.enumerated()), id: \.element.id) { index, device in
                HStack(spacing: 10) {
                    Image(systemName: device.isLocal ? Icon.laptop : Icon.phone)
                        .font(.system(size: 12))
                        .foregroundStyle(Palette.t3)
                        .frame(width: 18)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(device.name).font(.ui(TypeSize.ui))
                        Text(devices.lastSeenText(device))
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                    }
                    Spacer()
                    if devices.canRevoke(device) {
                        Button("Revoke") { revoking = device }
                            .buttonStyle(.nest(.danger))
                            .disabled(devices.revoking.contains(device.id))
                    }
                }
                .padding(.vertical, 6)
                .overlay(alignment: .top) {
                    if index > 0 {
                        Separator()
                    }
                }
            }
            if let code = devices.pairingCode {
                PairingCodeView(code: code)
            } else {
                HStack {
                    Text("Use Nest on your iPhone with a one-time code.")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                    Spacer()
                    Button {
                        createCode()
                    } label: {
                        Label("Pair a device", systemImage: Icon.plus)
                    }
                    .buttonStyle(.nest(.soft))
                    .disabled(devices.isCreatingCode)
                }
                .padding(.top, 8)
            }
        }
        .task { try? await devices.load() }
        .confirmationDialog(
            "Revoke \(revoking?.name ?? "this device")?", isPresented: revokeBinding,
            titleVisibility: .visible
        ) {
            Button("Revoke", role: .destructive) {
                if let device = revoking {
                    revoke(device)
                }
            }
            Button("Cancel", role: .cancel) { revoking = nil }
        } message: {
            Text("It stops working at once and has to be paired again.")
        }
    }

    private var revokeBinding: Binding<Bool> {
        Binding(get: { revoking != nil }, set: { if !$0 { revoking = nil } })
    }

    private func createCode() {
        Task {
            do {
                try await shell.model.devices.createPairingCode()
            } catch {
                shell.show(error, doing: "Could not create a pairing code")
            }
        }
    }

    private func revoke(_ device: Device) {
        revoking = nil
        Task {
            do {
                try await shell.model.devices.revoke(device)
                shell.show("Revoked \(device.name)", kind: .done)
            } catch {
                shell.show(error, doing: "Could not revoke \(device.name)")
            }
        }
    }
}

/// The one-time code, large, with its countdown and where to enter it.
private struct PairingCodeView: View {
    static let id = "pairing-code"

    let code: PairingCode
    @Environment(Shell.self) private var shell

    var body: some View {
        let devices = shell.model.devices
        VStack(spacing: 8) {
            Text(code.code)
                .font(.mono(26, .semibold))
                .tracking(5)
                .textSelection(.enabled)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(devices.expiryText(at: context.date))
                    .font(.ui(TypeSize.meta))
                    .monospacedDigit()
                    .foregroundStyle(
                        devices.secondsLeft(at: context.date) > 0
                            ? Palette.t2 : StatusTone.failed.color)
            }
            Text("Open your tailnet address in Safari on the iPhone, then enter this code.")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .multilineTextAlignment(.center)
            HStack(spacing: 6) {
                Button("New code") {
                    Task { try? await devices.createPairingCode() }
                }
                .buttonStyle(.nest(.plain))
                Button("Done") { devices.clearPairingCode() }
                    .buttonStyle(.nest(.soft))
            }
            .padding(.top, 2)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 14)
        .softFill()
        .padding(.top, 8)
        .id(Self.id)
    }
}
