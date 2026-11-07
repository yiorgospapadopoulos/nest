import NestKit
import SwiftUI

/// Each engine's accounts, one in use per engine, through the engines' own sign-ins (B98),
/// then every other engine the daemon lists as one More engines section (B107), the local
/// models (B106), first when the user chose them only, and the `gh` login (B81).
struct AccountsPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let localFirst = shell.model.local.localOnly
        if localFirst {
            LocalModelsSection()
        }
        EngineAccounts(provider: ProviderInfo.claude)
        EngineAccounts(provider: EngineMark.codex)
        let others = EngineSetup.others(shell.providers.providers)
        if !others.isEmpty {
            MoreEnginesSection(setups: others)
        }
        if !localFirst {
            LocalModelsSection()
        }
        GitHubSection()
    }
}

/// An engine's accounts as a radio group: the check marks the one turns run on, and a click
/// on another signed-in row moves it. Then Add and the Resets menu.
private struct EngineAccounts: View {
    let provider: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.accounts
        let engine = AccountText.engine(provider)
        SettingsSection(title: "", bare: true) {
            AccountsHeader(engine: provider, title: engine)
            VStack(alignment: .leading, spacing: 0) {
                ForEach(store.accounts(of: provider)) { account in
                    AccountRow(account: account)
                    if let error = account.error {
                        SettingsFailure(text: "Signing in failed: \(error)")
                    }
                }
            }
            .overlay(alignment: .top) { Separator() }
            .accessibilityElement(children: .contain)
            .accessibilityLabel("\(engine) account in use")
            // The sign-in page would open on this Mac, not where the remote engine runs.
            if shell.isRemote {
                RemoteSignIn(provider: provider)
            }
            HStack(spacing: 6) {
                if !shell.isRemote {
                    Button {
                        shell.addAccount(provider)
                    } label: {
                        Label("Add \(engine) account", systemImage: Icon.plus)
                    }
                    .buttonStyle(.nest(.soft))
                }
                // Claude Code keeps no banked resets.
                if provider == EngineMark.codex {
                    BankedResetsButton(provider: provider)
                }
            }
            .padding(.top, 10)
        }
        .task { try? await store.load() }
    }
}

/// The engine's banked resets: the count available on the button, and each signed-in
/// account's resets, read when opened, each with Use, which asks first.
private struct BankedResetsButton: View {
    let provider: String
    @Environment(Shell.self) private var shell
    @State private var open = false
    @State private var using: (account: EngineAccount, credit: BankedCredit)?

    var body: some View {
        let store = shell.model.accounts
        Button {
            open.toggle()
        } label: {
            HStack(spacing: 8) {
                Text(AccountText.bankedResetsTitle(store.bankedAvailable(provider)))
                Image(systemName: Icon.chevron)
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(Palette.t2)
            }
        }
        .buttonStyle(.nest(.soft))
        .popover(isPresented: $open, arrowEdge: .bottom) {
            BankedResetsList(provider: provider) { account, credit in
                open = false
                using = (account, credit)
            }
            .environment(shell)
        }
        .confirmationDialog(
            "Use a banked reset on \(using?.account.title ?? "this account")?",
            isPresented: Binding(get: { using != nil }, set: { if !$0 { using = nil } }),
            titleVisibility: .visible
        ) {
            Button("Use") { use() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Its current Codex limits reset now.")
        }
    }

    private func use() {
        guard let using else { return }
        let store = shell.model.accounts
        shell.settingsChange("Could not use the banked reset") {
            let outcome = try await store.useBankedReset(using.account.id, credit: using.credit.id)
            shell.show(AccountText.useOutcome(outcome), kind: outcome == .reset ? .done : .info)
        }
    }
}

/// Each signed-in account of the engine with its banked resets, or none.
struct BankedResetsList: View {
    let provider: String
    let use: (EngineAccount, BankedCredit) -> Void
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.accounts
        VStack(alignment: .leading, spacing: 0) {
            ForEach(store.accounts(of: provider).filter { $0.signedIn == true }) { account in
                let credits = store.bankedResets[account.id]?.credits
                SettingsSection(title: account.title, bare: true) {
                    if (account.bankedResets?.available ?? 0) == 0 && credits?.isEmpty != false {
                        Text("No banked resets")
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .padding(.vertical, 6)
                    } else if let credits {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(credits) { credit in
                                SettingsListRow(
                                    title: AccountText.creditTitle(credit),
                                    detail: AccountText.creditExpiry(credit, calendar: .current)
                                ) {
                                    EmptyView()
                                } trailing: {
                                    Button("Use") { use(account, credit) }
                                        .buttonStyle(.nest(.soft))
                                }
                            }
                        }
                        .overlay(alignment: .top) { Separator() }
                    } else {
                        Fireflies().padding(.vertical, 6)
                    }
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.bottom, 14)
        .frame(width: 300, alignment: .leading)
        .task { await store.loadBankedResets(provider) }
    }
}

/// What a row asks before it signs out of or removes its account.
private enum AccountConfirmation: Identifiable {
    case signOut, remove

    var id: Self { self }
}

/// One account: the check and its mark, its title with the plan and email, then its two
/// limits and login, or what signing in waits on, and its menu.
private struct AccountRow: View {
    let account: EngineAccount
    @Environment(Shell.self) private var shell
    @State private var renaming = false
    @State private var confirming: AccountConfirmation?

    var body: some View {
        SettingsListRow(
            title: account.title, detail: AccountText.detail(account),
            rename: rename
        ) {
            SettingsCheckBox(on: account.active)
                .accessibilityElement()
                .accessibilityLabel(
                    "Use \(account.title) for \(AccountText.engine(account.provider))"
                )
                .accessibilityAddTraits(account.active ? [.isButton, .isSelected] : .isButton)
                .accessibilityAction { activate(account.id) }
            AccountMark(account: account)
        } trailing: {
            AccountControls(account: account, renaming: $renaming, confirming: $confirming)
        }
        .contentShape(Rectangle())
        .onTapGesture { activate(account.id) }
        .focusable()
        .focusEffectDisabled()
        .onKeyPress(.space) {
            activate(account.id)
            return .handled
        }
        .onKeyPress(keys: [.upArrow, .downArrow]) { press in
            let offset = press.key == .upArrow ? -1 : 1
            guard let next = shell.model.accounts.neighbour(of: account.id, by: offset) else {
                return .ignored
            }
            activate(next)
            return .handled
        }
        .modifier(AccountConfirmations(account: account, confirming: $confirming))
    }

    private var rename: (initial: String, done: (String?) -> Void)? {
        guard renaming else { return nil }
        return (initial: account.name ?? account.title, done: { finishRename($0) })
    }

    private func finishRename(_ text: String?) {
        renaming = false
        guard let text else { return }
        let store = shell.model.accounts
        let id = account.id
        shell.settingsChange("Could not rename \(account.title)") {
            try await store.rename(id, to: text)
        }
    }

    /// A signed-out account does not take the check.
    private func activate(_ id: String) {
        let store = shell.model.accounts
        shell.settingsChange("Could not switch accounts") { try await store.activate(id) }
    }
}

/// The row's trailing side: signing in waits on the browser; otherwise the limits of a
/// signed-in account, its login, Sign in when signed out, and the menu.
private struct AccountControls: View {
    let account: EngineAccount
    @Binding var renaming: Bool
    @Binding var confirming: AccountConfirmation?
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.accounts
        if account.signingIn {
            Fireflies()
            Text("Finish in the browser")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            Button("Cancel") {
                shell.settingsChange("Could not cancel signing in") {
                    try await store.cancelSignIn(account.id)
                }
            }
            .buttonStyle(.nest(.soft))
        } else {
            let signedIn = account.signedIn == true
            // With local models, signing in is a choice, not a need (B106).
            let optional = shell.model.local.signInOptional
            if signedIn {
                AccountLimits(limits: account.limits)
            }
            StatusLabel(
                tone: signedIn ? .review : .done,
                label: AccountText.state(account, optional: optional), hollow: !signedIn)
            if !signedIn && !shell.isRemote {
                Button("Sign in") { shell.signIn(account.id) }
                    .buttonStyle(.nest(optional ? .soft : .primary))
            }
            RowActionsMenu(title: account.title) {
                Button("Rename…") { renaming = true }
                if signedIn {
                    Button("Sign out") { confirming = .signOut }
                }
                if !account.first {
                    Divider()
                    Button("Remove", role: .destructive) { confirming = .remove }
                }
            }
            .disabled(store.isBusy(account.id))
        }
    }
}

extension Shell {
    /// Settings > Accounts' sign-in, the one path the setup guide uses too.
    func addAccount(_ provider: String) {
        let store = model.accounts
        settingsChange("Could not add a \(AccountText.engine(provider)) account") {
            if let page = try await store.add(provider) {
                NSWorkspace.shared.open(page)
            }
        }
    }

    func signIn(_ account: String) {
        let store = model.accounts
        settingsChange("Could not start signing in") {
            if let page = try await store.signIn(account) {
                NSWorkspace.shared.open(page)
            }
        }
    }
}

/// While connected to a remote daemon (B105): sign in on its machine, with the command to
/// run there and Copy.
struct RemoteSignIn: View {
    let provider: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let command = DaemonText.signInCommand(provider)
        VStack(alignment: .leading, spacing: 8) {
            Text(DaemonText.signInNote(shell.machineName))
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t2)
            HStack(spacing: 8) {
                Text(command)
                    .font(.mono(TypeSize.meta))
                    .foregroundStyle(Palette.t1)
                    .textSelection(.enabled)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Palette.soft, in: .rounded(Radius.card))
                Button {
                    shell.copyText(command)
                } label: {
                    Label("Copy", systemImage: Icon.copy).labelStyle(TightLabelStyle())
                }
                .buttonStyle(.nest(height: 28))
                .help("Copy the command")
            }
        }
        .padding(.top, 10)
    }
}

/// Sign out and Remove ask first, as Sign out did before B98.
private struct AccountConfirmations: ViewModifier {
    let account: EngineAccount
    @Binding var confirming: AccountConfirmation?
    @Environment(Shell.self) private var shell

    func body(content: Content) -> some View {
        content.confirmationDialog(
            confirming == .remove ? "Remove \(account.title)?" : "Sign out of \(account.title)?",
            isPresented: Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } }),
            titleVisibility: .visible, presenting: confirming
        ) { confirmation in
            Button(confirmation == .remove ? "Remove" : "Sign out", role: .destructive) {
                confirm(confirmation)
            }
            Button("Cancel", role: .cancel) {}
        } message: { confirmation in
            if confirmation == .signOut, account.first, !shell.model.local.signInOptional {
                Text(signOutNote)
            }
        }
    }

    /// The first account is the engine's own login on this Mac.
    private var signOutNote: String {
        account.provider == ProviderInfo.claude
            ? "Claude Code on this Mac signs out too. Chats cannot run until you sign in again."
            : "Codex on this Mac signs out too. Codex chats cannot run until you sign in again."
    }

    private func confirm(_ confirmation: AccountConfirmation) {
        let store = shell.model.accounts
        let id = account.id
        switch confirmation {
        case .signOut:
            shell.settingsChange("Could not sign out") { try await store.signOut(id) }
        case .remove:
            shell.settingsChange("Could not remove \(account.title)") {
                try await store.remove(id)
            }
        }
    }
}

/// Claude's accounts show their initials, Codex's the OpenAI mark, as before B98.
private struct AccountMark: View {
    let account: EngineAccount

    var body: some View {
        if account.provider == ProviderInfo.claude {
            Avatar(name: account.title, size: 30)
        } else {
            OpenAIMark(size: 18)
                .foregroundStyle(Palette.t2)
                .frame(width: 26, height: 26)
                .background(Palette.soft, in: .rounded(6))
        }
    }
}

/// Every window, each a thin bar under its percent and reset time in full, as the usage
/// popover draws them.
private struct AccountLimits: View {
    let limits: [AccountLimit]

    var body: some View {
        TimelineView(.everyMinute) { context in
            VStack(alignment: .leading, spacing: 3) {
                ForEach(limits, id: \.label) { limit in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(AccountText.limitLine(limit, now: context.date, calendar: .current))
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .monospacedDigit()
                            .fixedSize()
                        Meter(value: limit.window.utilization, height: 3, color: Palette.t1)
                    }
                }
            }
            // At least the width it had, wider when a line needs it.
            .frame(minWidth: 132, alignment: .leading)
            .fixedSize(horizontal: true, vertical: false)
            .accessibilityElement(children: .combine)
        }
    }
}

/// The engines past Claude and Codex (B107), one compact row each, as one section.
private struct MoreEnginesSection: View {
    let setups: [EngineSetup]

    var body: some View {
        SettingsSection(title: "", bare: true) {
            AccountsHeader(title: "More engines") { AccountsSymbol(name: Icon.agent) }
            MoreEngineRows(setups: setups)
        }
    }
}

/// The rows themselves, as Settings > Accounts and the setup guide's Engine step show them.
struct MoreEngineRows: View {
    let setups: [EngineSetup]
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(setups, id: \.name) { setup in
                MoreEngineRow(setup: setup)
            }
        }
        .overlay(alignment: .top) { Separator() }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("More engines")
        // A sign-in in Terminal sends no event, so the engines are asked again on the way back.
        .onReceive(
            NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)
        ) { _ in
            Task { await shell.providers.load(refresh: true) }
        }
    }
}

/// An engine's name with its version under it, its labels and the git warning mark, then
/// its state and its one action. The engine runs on its account in use, the first one
/// unless another was chosen before.
private struct MoreEngineRow: View {
    let setup: EngineSetup
    @Environment(Shell.self) private var shell
    @State private var addingKey = false
    @State private var key = ""
    @State private var removingKey = false
    // A tooltip does not show inside this row, so the warning opens on hover instead.
    @State private var showingWarning = false

    private var accountID: String {
        shell.model.accounts.accounts(of: setup.name).first(where: \.active)?.id
            ?? "\(setup.name)-main"
    }

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(setup.title).font(.ui(TypeSize.ui, .medium)).lineLimit(1)
                    ForEach(setup.labels, id: \.self) { label in
                        Text(label)
                            .font(.ui(10, .medium))
                            .foregroundStyle(Palette.t2)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 1)
                            .background(Palette.soft, in: .rounded(4))
                    }
                    if let warning = setup.gitWarning {
                        Image(systemName: Icon.warning)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(StatusTone.waiting.color)
                            .contentShape(Rectangle())
                            .onHover { showingWarning = $0 }
                            .popover(isPresented: $showingWarning, arrowEdge: .bottom) {
                                Text(warning)
                                    .font(.ui(TypeSize.meta))
                                    .fixedSize(horizontal: false, vertical: true)
                                    .frame(width: 240, alignment: .leading)
                                    .padding(10)
                            }
                            .accessibilityLabel(warning)
                    }
                }
                if let version = setup.version {
                    Text(version)
                        .font(.mono(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
                if let failure = setup.failure {
                    Text(failure)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 8)
            HStack(spacing: 6) {
                if setup.installing {
                    Fireflies()
                }
                StatusLabel(
                    tone: setup.ready ? .review : .done, label: setup.state, hollow: !setup.ready)
                action
            }
        }
        .padding(.vertical, 8)
        .overlay(alignment: .bottom) { Separator() }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(setup.title)
        .confirmationDialog(
            "Remove the \(setup.title) key?", isPresented: $removingKey,
            titleVisibility: .visible
        ) {
            Button("Remove", role: .destructive) { removeKey() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("\(setup.title) chats cannot run until you save a key again.")
        }
    }

    @ViewBuilder private var action: some View {
        switch setup.action {
        case .none:
            EmptyView()
        case .install(let again):
            Button(again ? "Install again" : "Install") { install() }
                .buttonStyle(.nest(.primary))
        case .signIn(let command):
            // The login runs where the daemon does, so not in this Mac's Terminal.
            if shell.isRemote {
                Button("Copy sign-in command") { shell.copyText(command) }
                    .buttonStyle(.nest(.soft))
            } else {
                Button("Sign in") { openTerminal(command) }
                    .buttonStyle(.nest(.primary))
            }
        case .addKey(let placeholder):
            if addingKey {
                CardField(
                    placeholder: placeholder, text: $key, submit: saveKey, focusOnAppear: true,
                    secure: true
                )
                .frame(width: 220)
                Button("Save") { saveKey() }
                    .buttonStyle(.nest(.primary))
                    .disabled(key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            } else {
                Button("Add key") { addingKey = true }
                    .buttonStyle(.nest(.primary))
            }
        case .removeKey:
            Button("Remove key") { removingKey = true }
                .buttonStyle(.nest(.soft))
        }
    }

    private func install() {
        let providers = shell.providers
        let name = setup.name
        shell.settingsChange("Could not install \(setup.title)") {
            try await providers.install(name)
        }
    }

    /// The key goes to the daemon only, which keeps it in the Keychain; the field empties.
    private func saveKey() {
        let typed = key
        guard !typed.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        key = ""
        addingKey = false
        let store = shell.model.accounts
        let providers = shell.providers
        let id = accountID
        shell.settingsChange("Could not save the key") {
            try await store.saveKey(id, key: typed)
            await providers.load()
        }
    }

    private func removeKey() {
        let store = shell.model.accounts
        let providers = shell.providers
        let id = accountID
        shell.settingsChange("Could not remove the key") {
            try await store.removeKey(id)
            await providers.load()
        }
    }

    /// Asks the daemon for the account's login command, which may differ from the
    /// engine's for an added account, then runs it in Terminal.
    private func openTerminal(_ fallback: String) {
        let store = shell.model.accounts
        let id = accountID
        shell.settingsChange("Could not open Terminal") {
            let started = try await store.startSignIn(id)
            try await TerminalSignIn.run(started.loginCommand ?? fallback)
        }
    }
}

private struct GitHubSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let accounts = shell.model.accounts
        let github = accounts.github
        SettingsSection(title: "", bare: true) {
            AccountsHeader(title: "GitHub") { AccountsSymbol(name: Icon.pullRequest) }
            SettingsListRow(title: github?.login ?? "GitHub") {
                SettingsBadge(text: "gh")
            } trailing: {
                if let github {
                    StatusLabel(
                        tone: github.state == .signedIn ? .review : .waiting,
                        label: AccountText.githubState(github.state),
                        hollow: github.state != .signedIn)
                }
                if accounts.isCheckingGitHub {
                    Fireflies()
                }
                Button("Check again") {
                    shell.settingsChange("Could not check the GitHub login") {
                        try await accounts.checkGitHub()
                    }
                }
                .buttonStyle(.nest(.soft))
                .disabled(accounts.isCheckingGitHub)
            }
            .overlay(alignment: .top) { Separator() }
        }
        .task { try? await accounts.loadGitHub() }
    }
}
