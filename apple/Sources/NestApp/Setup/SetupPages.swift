import AppKit
import NestKit
import SwiftUI

/// The open step's page.
struct SetupPage: View {
    let flow: SetupFlow
    let engineReady: Bool
    @Environment(Shell.self) private var shell

    var body: some View {
        let check = shell.setupChecks?.first { $0.id == flow.step.id }
        VStack(alignment: .leading, spacing: 12) {
            switch flow.step {
            case .engine: EnginePage()
            case .tailscale: TailscalePage(check: check)
            case .notifications: NotificationsStepPage()
            case .dictation: DictationStepPage()
            case .firstChat: FirstChatPage(disabled: !flow.canFinish(engineReady: engineReady))
            default: GenericPage(check: check)
            }
        }
    }
}

/// A check's message, its fix and Check again. On a Mac, git's command has an Install
/// button beside it, and GitHub's page is a Download.
private struct GenericPage: View {
    let check: SetupCheck?

    var body: some View {
        if let line = check.flatMap({ $0.message.isEmpty ? $0.detail : $0.message }) {
            SetupLine(text: line)
        }
        if let check, let fix = check.fix {
            if check.id == SetupStep.git.id, fix.value == GitInstall.command {
                GitInstall()
            } else {
                FixAction(fix: fix, open: check.id == SetupStep.github.id ? "Download" : "Open")
            }
        }
        CheckAgain()
        if check?.id == SetupStep.git.id {
            GitWatch(passed: check?.state == .ok)
        }
    }
}

/// Apple's command line tools, which bring git: the line to paste, and Install, which runs
/// it. It only opens Apple's own installer window.
private struct GitInstall: View {
    static let command = "xcode-select --install"
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 8) {
            CopyableCommand(command: Self.command)
            Button("Install") {
                do {
                    try DetachedSpawner().spawn("/usr/bin/xcode-select", ["--install"])
                } catch {
                    shell.show(error, doing: "Could not open Apple's installer")
                }
            }
            .buttonStyle(.nest(.primary))
        }
    }
}

/// While git's page is open, its check runs again every few seconds until git passes, as
/// Apple's installer finishes on its own.
private struct GitWatch: View {
    let passed: Bool
    @Environment(Shell.self) private var shell

    var body: some View {
        Color.clear.frame(width: 0, height: 0)
            .task(id: passed) {
                let store = shell.model.setup
                while !passed, !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(5))
                    if !store.checking, !Task.isCancelled {
                        await store.refresh()
                    }
                }
            }
    }
}

/// Claude Code, Codex or local models, through the same actions as Settings > Accounts, and
/// every other engine under More engines, opened here: the guide never leaves for Settings.
private struct EnginePage: View {
    @Environment(Shell.self) private var shell
    @State private var more = false

    var body: some View {
        let accounts = shell.model.accounts
        let local = shell.model.local
        let signedIn = accounts.accounts.filter { $0.signedIn == true }.count
        let others = EngineSetup.others(shell.providers.providers)
        let othersReady = others.filter(\.ready).count
        VStack(alignment: .leading, spacing: 8) {
            EngineRow(provider: ProviderInfo.claude, title: "Claude Code")
            EngineRow(provider: EngineMark.codex, title: "Codex")
            EngineCard(title: "Local models") {
                if local.localOnly {
                    StepMark(mark: .ok)
                } else {
                    Button("Use local models only") {
                        shell.settingsChange("Could not continue") {
                            try await local.useLocalOnly()
                            await local.load()
                            shell.recheckSetup()
                        }
                    }
                    .buttonStyle(.nest(.soft))
                }
            }
            if !others.isEmpty {
                EngineCard(title: "More engines") {
                    if othersReady > 0 {
                        StepMark(mark: .ok)
                    }
                    Button {
                        more.toggle()
                    } label: {
                        HStack(spacing: 5) {
                            Text(more ? "Hide" : "Show")
                            Image(systemName: Icon.chevron)
                                .font(.system(size: 8, weight: .semibold))
                                .rotationEffect(.degrees(more ? 180 : 0))
                        }
                    }
                    .buttonStyle(.nest(.soft))
                    .accessibilityValue(more ? "Shown" : "Hidden")
                }
                if more {
                    MoreEngineRows(setups: others).padding(.horizontal, 4)
                }
            }
            if shell.isRemote {
                RemoteSignIn(provider: ProviderInfo.claude).padding(.top, 4)
                RemoteSignIn(provider: EngineMark.codex).padding(.top, 4)
            }
        }
        .task {
            try? await accounts.load()
            await local.load()
            await shell.providers.load()
        }
        // A sign-in ends in the browser or Terminal; the change makes the check worth asking.
        .onChange(of: signedIn) { if signedIn > 0 { shell.recheckSetup() } }
        .onChange(of: othersReady) { if othersReady > 0 { shell.recheckSetup() } }
    }
}

private struct EngineRow: View {
    let provider: String
    let title: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let account = shell.model.accounts.accounts(of: provider).first
        EngineCard(title: title) {
            if account?.signedIn == true {
                StepMark(mark: .ok)
            } else if !shell.isRemote {
                Button("Sign in") {
                    if let account {
                        shell.signIn(account.id)
                    } else {
                        shell.addAccount(provider)
                    }
                }
                .buttonStyle(.nest(.soft))
            }
        }
    }
}

private struct EngineCard<Trailing: View>: View {
    let title: String
    @ViewBuilder let trailing: () -> Trailing

    var body: some View {
        HStack(spacing: 12) {
            Text(title).font(.ui(TypeSize.reading, .medium))
            Spacer(minLength: 8)
            trailing()
        }
        .padding(.horizontal, 16)
        .frame(minHeight: 48)
        .background(Palette.soft, in: .rounded(9))
        .overlay(RoundedRectangle.rounded(9).strokeBorder(Palette.divider))
    }
}

/// Tailscale step by step, as far as the check says it has come: installed, signed in,
/// shared, then the pairing code in place, never before Nest is reachable (B130).
private struct TailscalePage: View {
    let check: SetupCheck?
    @Environment(Shell.self) private var shell

    var body: some View {
        let devices = shell.model.devices
        let stage = TailscaleStage(check)
        let pairing = stage.reachable && check?.state != .ok
        VStack(alignment: .leading, spacing: 12) {
            if let check {
                if stage == .install || stage == .connect {
                    MarkLine(mark: .now, text: check.message)
                } else {
                    MarkLine(mark: .ok, text: "Tailscale is running")
                }
                if stage == .install, let fix = check.fix {
                    FixAction(fix: fix)
                }
                if stage == .share {
                    // Tailscale's link to turn HTTPS on for the tailnet, then share again.
                    if let fix = check.fix {
                        MarkLine(mark: .now, text: check.message)
                        FixAction(fix: fix)
                    }
                    ShareButton()
                }
                if stage.reachable {
                    MarkLine(mark: .ok, text: "Shared with your devices at \(check.detail ?? "")")
                }
                if check.state == .ok {
                    MarkLine(mark: .ok, text: "Your iPhone is paired")
                }
            }
            if pairing {
                MarkLine(mark: .now, text: "Open that address on your iPhone and enter this code")
                if let code = devices.pairingCode {
                    PairingCodeView(code: code).padding(.leading, 22)
                }
            } else if stage != .share {
                CheckAgain()
            }
        }
        .onChange(of: pairing, initial: true) {
            if pairing {
                shell.settingsChange("Could not create a pairing code") {
                    try await devices.createPairingCode()
                }
            }
        }
        .onDisappear { devices.clearPairingCode() }
    }
}

/// Sharing Nest on the tailnet, which the daemon runs itself: no Terminal.
private struct ShareButton: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.setup
        HStack(spacing: 8) {
            Button("Share with my devices") {
                shell.settingsChange("Could not share Nest") { try await store.shareTailscale() }
            }
            .buttonStyle(.nest(.primary))
            .disabled(store.sharing)
            if store.sharing {
                Fireflies()
            }
        }
    }
}

/// One switch per way a notification reaches the user, each showing its real state (design
/// C): this Mac's and the phone's push. ntfy is in Settings only.
private struct NotificationsStepPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let permissions = shell.permissions
        let devices = shell.model.devices
        SwitchGroup {
            PermissionRow(
                title: "This Mac", answer: permissions.notifications,
                address: SystemAnswers.notificationSettings
            ) { await permissions.askNotifications() }
            SwitchRow(
                title: "iPhone", line: "Turn on in Account > Notifications on the phone",
                divided: true
            ) {
                // Turned on on the phone itself, so it only shows here.
                Switch(isOn: (devices.pushDevices ?? 0) > 0) {}
                    .disabled(true)
                    .accessibilityLabel("iPhone notifications")
            }
        }
        .task { try? await devices.loadPushStatus() }
        // A phone may have turned its push on meanwhile.
        .onReceive(
            NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)
        ) { _ in Task { try? await devices.loadPushStatus() } }
    }
}

/// The microphone and speech recognition, a switch each; one not asked yet asks when turned
/// on.
private struct DictationStepPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let permissions = shell.permissions
        SwitchGroup {
            PermissionRow(
                title: "Microphone", answer: permissions.microphone,
                address: SystemAnswers.microphoneSettings
            ) { await permissions.askDictation() }
            PermissionRow(
                title: "Speech recognition", answer: permissions.speech,
                address: SystemAnswers.speechSettings, divided: true
            ) { await permissions.askDictation() }
        }
    }
}

/// One rounded group of rows, as System Settings has them.
private struct SwitchGroup<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0, content: content)
            .background(Palette.soft, in: .rounded(10))
            .overlay(RoundedRectangle.rounded(10).strokeBorder(Palette.divider))
    }
}

/// A row of the group: its title, a line under it, and its switch.
private struct SwitchRow<Line: View, Control: View>: View {
    let title: String
    var divided = false
    @ViewBuilder let line: () -> Line
    @ViewBuilder let control: () -> Control

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.ui(TypeSize.reading, .medium))
                line()
            }
            Spacer(minLength: 8)
            control()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .frame(minHeight: 48)
        .overlay(alignment: .top) {
            if divided {
                Separator()
            }
        }
    }
}

extension SwitchRow where Line == SwitchLine {
    init(
        title: String, line: String?, divided: Bool = false,
        @ViewBuilder control: @escaping () -> Control
    ) {
        self.init(
            title: title, divided: divided, line: { SwitchLine(text: line) }, control: control)
    }
}

private struct SwitchLine: View {
    let text: String?

    var body: some View {
        if let text {
            Text(text)
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t2)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// A permission macOS answers: on once allowed. One not asked yet asks when turned on; one
/// blocked shows off with a short red note and the way to System Settings, the only place
/// it can change, as for turning an allowed one off.
private struct PermissionRow: View {
    let title: String
    let answer: SystemPermission
    let address: String
    var divided = false
    let ask: @MainActor () async -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        SwitchRow(title: title, divided: divided) {
            switch answer {
            case .refused:
                HStack(spacing: 4) {
                    Text("Blocked in System Settings.")
                        .foregroundStyle(StatusTone.failed.color)
                    Button("Open") { shell.permissions.openSettings(address) }
                        .buttonStyle(.plain)
                        .underline()
                        .foregroundStyle(Palette.t1)
                        .pointerStyle(.link)
                }
                .font(.ui(TypeSize.small))
            case .restricted:
                SwitchLine(text: "Restricted on this Mac.")
            case .notAsked:
                SwitchLine(text: "Not asked yet")
            case .allowed:
                EmptyView()
            }
        } control: {
            Switch(isOn: answer == .allowed) {
                if answer == .notAsked {
                    Task { await ask() }
                } else {
                    shell.permissions.openSettings(address)
                }
            }
            .disabled(answer == .restricted)
            .accessibilityLabel(title)
        }
    }
}

/// Open a chat, on the cheapest model of the engine, or Add a project; both finish the guide.
private struct FirstChatPage: View {
    let disabled: Bool
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 8) {
            Button("Open a chat") {
                let model = shell.firstChatModel
                shell.finishGuide { shell.openGeneralChat(model) }
            }
            .buttonStyle(.nest(.primary, height: 30))
            Button("Add a project") {
                shell.finishGuide {
                    shell.closeGuide()
                    shell.openSettings(.addProject)
                }
            }
            .buttonStyle(.nest(.soft, height: 30))
        }
        .disabled(disabled)
    }
}
