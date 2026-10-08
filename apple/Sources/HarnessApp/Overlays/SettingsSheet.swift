import HarnessKit
import SwiftUI

/// Settings: appearance, defaults for new chats, the usage refresh, Claude Code chats,
/// stuck chats, notifications, paired devices and the account.
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
                Avatar(name: shell.accountName, size: 44)
                VStack(alignment: .leading, spacing: 1) {
                    Text(shell.accountName).font(.ui(TypeSize.subhead, .bold))
                    Text(agents.plan).font(.ui(TypeSize.small)).foregroundStyle(Palette.t2)
                    if let email = agents.email {
                        Text(email)
                            .font(.ui(TypeSize.small))
                            .foregroundStyle(Palette.t3)
                            .textSelection(.enabled)
                    }
                    Text("Signed in through Claude Code")
                        .font(.ui(TypeSize.small))
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
            SheetRow(label: "Glass") {
                HStack(spacing: 8) {
                    ForEach(DesignTokens.GlassTheme.all, id: \.name) { style in
                        GlassChoice(style: style, selected: settings.glass == style) {
                            settings.glass = style
                        }
                    }
                }
                .fixedSize()
            }
            SheetRow(label: "Accent") {
                HStack(spacing: 8) {
                    ForEach(AccentName.allCases, id: \.self) { name in
                        Swatch(name: name, selected: settings.accent == name) {
                            settings.accent = name
                        }
                    }
                }
            }
            SheetRow(label: "Your messages") {
                Segmented(
                    options: [(BubbleStyle.accent, "Accent"), (.neutral, "Neutral")],
                    selection: settings.bubble
                ) { settings.bubble = $0 }
            }
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
                .overlay(Circle().strokeBorder(.black.opacity(0.12)))
                .overlay {
                    if selected {
                        Image(systemName: Icon.check)
                            .font(.system(size: 11, weight: .heavy))
                            .foregroundStyle(Color(accent.on))
                    }
                }
                .frame(width: 26, height: 26)
                .padding(3)
                .overlay {
                    if selected {
                        Circle().strokeBorder(Palette.t1, lineWidth: 1.5)
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

/// A glass theme's preview: a small pane of that glass over a bit of desktop, with the
/// theme's name under it.
private struct GlassChoice: View {
    let style: GlassStyle
    let selected: Bool
    let pick: () -> Void

    var body: some View {
        Button(action: pick) {
            VStack(spacing: 4) {
                GlassSample()
                    .environment(\.glass, GlassPalette.of(style))
                    .frame(width: 62, height: 38)
                    .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 9, style: .continuous)
                            .strokeBorder(Palette.hair)
                    )
                    .padding(2)
                    .overlay {
                        if selected {
                            RoundedRectangle(cornerRadius: 11, style: .continuous)
                                .strokeBorder(Palette.t1, lineWidth: 1.5)
                        }
                    }
                Text(style.displayName)
                    .font(.ui(TypeSize.caption, selected ? .semibold : .regular))
                    .lineLimit(1)
                    .foregroundStyle(selected ? Palette.t1 : Palette.t2)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(style.summary)
        .accessibilityLabel("\(style.displayName) glass")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// The mockup's `.wpt` preview: a cool desktop with a warm spot, under a pane of glass
/// drawn flat with the theme's tint, edges and shadow.
private struct GlassSample: View {
    @Environment(\.glass) private var glass
    @Environment(\.colorScheme) private var scheme

    private static let sky = Color(red: 0.77, green: 0.83, blue: 0.88)
    private static let moss = Color(red: 0.62, green: 0.70, blue: 0.61)
    private static let sun = Color(red: 0.95, green: 0.62, blue: 0.35)
    private static let night = Color(red: 0.07, green: 0.10, blue: 0.15)
    private static let nightMoss = Color(red: 0.14, green: 0.20, blue: 0.16)
    private static let ember = Color(red: 0.55, green: 0.35, blue: 0.22)

    var body: some View {
        let dark = scheme == .dark
        let shape = glass.rounded(min(glass.radius.pane, 7))
        ZStack {
            LinearGradient(
                colors: dark ? [Self.night, Self.nightMoss] : [Self.sky, Self.moss],
                startPoint: .top, endPoint: .bottom)
            Circle()
                .fill(dark ? Self.ember : Self.sun)
                .frame(width: 22, height: 22)
                .offset(x: 14, y: -6)
            shape
                .fill(glass.tint)
                .overlay(GlassEdges(shape: shape))
                .shadow(color: glass.shadow, radius: 3, y: 3)
                .padding(EdgeInsets(top: 6, leading: 8, bottom: 6, trailing: 8))
        }
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
                DropdownMenu(title: defaults.effort?.label ?? "Model default") {
                    ThinkingItems(
                        model: defaults.model, effort: defaults.effort, offersDefault: true
                    ) { effort in
                        change { try await agents.setDefaultEffort(effort) }
                    }
                }
            }
            SheetRow(label: "Permission mode") {
                DropdownMenu(title: defaults.permissionMode.label) {
                    ForEach(PermissionMode.selectable, id: \.self) { mode in
                        OptionItem(
                            title: mode.label, detail: mode.summary,
                            checked: defaults.permissionMode == mode
                        ) { change { try await agents.setDefaultPermissionMode(mode) } }
                    }
                }
            }
            SheetRow(label: "New chats work in") {
                Segmented(
                    options: [(SessionMode.inPlace, "In place"), (.worktree, "Worktree")],
                    selection: defaults.mode
                ) { mode in change { try await agents.setDefaultMode(mode) } }
            }
            Text("Shared with harness on your iPhone.")
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t3)
                .padding(.bottom, 6)
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

/// A fill-backed menu button, as the mockup's `.dd`.
struct DropdownMenu<Items: View>: View {
    let title: String
    @ViewBuilder let items: () -> Items
    @State private var hovering = false

    var body: some View {
        Menu {
            items()
        } label: {
            HStack(spacing: 10) {
                Text(title).font(.ui(TypeSize.callout, .semibold))
                Spacer(minLength: 0)
                Image(systemName: Icon.chevron)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Palette.t3)
            }
            .foregroundStyle(Palette.t1)
            .padding(.leading, 12)
            .padding(.trailing, 10)
            .frame(width: 170, height: 30)
            .background(
                hovering ? Palette.fill2 : Palette.fill, in: RoundedRectangle(cornerRadius: 9)
            )
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
                "While harness is on screen, a tiny check (about 400 tokens) keeps the 5 hour and weekly limits current. Refresh in the usage popover asks at once."
            )
            .font(.ui(TypeSize.small))
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
                .font(.ui(TypeSize.small))
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
            .font(.ui(TypeSize.small))
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
                        .font(.system(size: 13))
                        .foregroundStyle(Palette.t2)
                        .frame(width: 26, height: 26)
                        .background(Palette.fill2, in: RoundedRectangle(cornerRadius: 8))
                    VStack(alignment: .leading, spacing: 1) {
                        Text(device.name).font(.ui(TypeSize.body))
                        Text(devices.lastSeenText(device))
                            .font(.ui(TypeSize.caption))
                            .foregroundStyle(Palette.t3)
                    }
                    Spacer()
                    if devices.canRevoke(device) {
                        Button("Revoke") { revoking = device }
                            .buttonStyle(.card(.danger))
                            .disabled(devices.revoking.contains(device.id))
                    }
                }
                .padding(.vertical, 8)
                .overlay(alignment: .top) {
                    if index > 0 {
                        Rectangle().fill(Palette.hair).frame(height: 1)
                    }
                }
            }
            if let code = devices.pairingCode {
                PairingCodeView(code: code)
            } else {
                HStack {
                    Text("Use harness on your iPhone with a one-time code.")
                        .font(.ui(TypeSize.small))
                        .foregroundStyle(Palette.t3)
                    Spacer()
                    Button {
                        createCode()
                    } label: {
                        Label("Pair a device", systemImage: Icon.plus)
                    }
                    .buttonStyle(.harness(.plain))
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
                .font(.system(size: 34, weight: .bold, design: .monospaced))
                .tracking(6)
                .textSelection(.enabled)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Text(devices.expiryText(at: context.date))
                    .font(.ui(TypeSize.small, .semibold))
                    .monospacedDigit()
                    .foregroundStyle(
                        devices.secondsLeft(at: context.date) > 0
                            ? Palette.t2 : StatusTone.failed.textColor)
            }
            Text("Open your tailnet address in Safari on the iPhone, then enter this code.")
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t3)
                .multilineTextAlignment(.center)
            HStack(spacing: 8) {
                Button("New code") {
                    Task { try? await devices.createPairingCode() }
                }
                .buttonStyle(.harness(.ghost))
                Button("Done") { devices.clearPairingCode() }
                    .buttonStyle(.harness(.plain))
            }
            .padding(.top, 2)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16)
        .background(Palette.fill, in: RoundedRectangle(cornerRadius: 14))
        .padding(.top, 8)
        .id(Self.id)
    }
}
