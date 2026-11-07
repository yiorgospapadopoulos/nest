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

/// A check's message, its fix and Check again.
private struct GenericPage: View {
    let check: SetupCheck?

    var body: some View {
        if let line = check.flatMap({ $0.message.isEmpty ? $0.detail : $0.message }) {
            SetupLine(text: line)
        }
        if let fix = check?.fix {
            FixAction(fix: fix)
        }
        CheckAgain()
    }
}

/// Claude Code, Codex or local models, through the same actions as Settings > Accounts.
private struct EnginePage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let accounts = shell.model.accounts
        let local = shell.model.local
        let signedIn = accounts.accounts.filter { $0.signedIn == true }.count
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
            if shell.isRemote {
                RemoteSignIn(provider: ProviderInfo.claude).padding(.top, 4)
                RemoteSignIn(provider: EngineMark.codex).padding(.top, 4)
            }
        }
        .task {
            try? await accounts.load()
            await local.load()
        }
        // A sign-in ends in the browser; the accounts' change makes the check worth asking.
        .onChange(of: signedIn) { if signedIn > 0 { shell.recheckSetup() } }
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

/// The system's answer, with System Settings once refused, then the phone's own switch, then
/// ntfy, the optional part, as Settings > Notifications has them.
private struct NotificationsStepPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let permissions = shell.permissions
        let answer = permissions.notifications
        MarkLine(
            mark: answer == .allowed ? .ok : .now,
            text: SystemAnswers.line("Notifications", answer))
        if answer == .refused {
            OpenSystemSettings(address: SystemAnswers.notificationSettings)
        } else if answer == .notAsked {
            Button("Ask now") { Task { await permissions.askNotifications() } }
                .buttonStyle(.nest(.soft))
        }
        SetupLine(text: "Turn on notifications in Account > Notifications on your phone.")
        Text("ntfy")
            .font(.ui(TypeSize.ui, .semibold))
            .padding(.top, 16)
        SetupLine(text: "Push notifications through the ntfy app.")
        NtfySection()
    }
}

/// The microphone and speech recognition, a button that asks now, and System Settings once
/// refused.
private struct DictationStepPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let permissions = shell.permissions
        let answers = [
            ("Microphone", permissions.microphone, SystemAnswers.microphoneSettings),
            ("Speech Recognition", permissions.speech, SystemAnswers.speechSettings),
        ]
        ForEach(answers, id: \.0) { name, answer, address in
            MarkLine(
                mark: answer == .allowed ? .ok : .now, text: SystemAnswers.line(name, answer))
            if answer == .refused {
                OpenSystemSettings(address: address)
            }
        }
        if answers.contains(where: { $0.1 == .notAsked }) {
            Button("Ask now") { Task { await permissions.askDictation() } }
                .buttonStyle(.nest(.soft))
        }
    }
}

private struct OpenSystemSettings: View {
    let address: String
    @Environment(Shell.self) private var shell

    var body: some View {
        Button("Open System Settings") { shell.permissions.openSettings(address) }
            .buttonStyle(.nest(.soft))
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
