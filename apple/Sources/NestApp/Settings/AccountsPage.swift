import NestKit
import SwiftUI

/// The Claude Code login, through Claude Code's own commands, the Codex login through
/// Codex's own sign-in (B94), and the `gh` login (B81).
struct AccountsPage: View {
    var body: some View {
        ClaudeSection()
        CodexSection()
        GitHubSection()
    }
}

private struct ClaudeSection: View {
    @Environment(Shell.self) private var shell
    @State private var confirmingSignOut = false

    var body: some View {
        let accounts = shell.model.accounts
        let login = accounts.claude
        SettingsSection(title: "Claude", bare: true) {
            SettingsListRow(
                title: login?.email ?? shell.accountName,
                detail: login.flatMap(AccountText.claudeDetail)
            ) {
                Avatar(name: shell.accountName, size: 30)
            } trailing: {
                if let login {
                    StatusLabel(
                        tone: login.signedIn ? .review : .done,
                        label: login.signedIn ? "Signed in" : "Signed out", hollow: !login.signedIn)
                }
                if accounts.isSigningIn {
                    Fireflies()
                    Text("Finish in the browser")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                } else if login?.signedIn == true {
                    Button("Sign out") { confirmingSignOut = true }
                        .buttonStyle(.nest(.soft))
                        .disabled(accounts.isSigningOut)
                } else if login != nil {
                    Button("Sign in") {
                        shell.settingsChange("Could not start signing in") {
                            try await accounts.signIn()
                        }
                    }
                    .buttonStyle(.nest(.primary))
                }
            }
            .overlay(alignment: .top) { Separator() }
            if let error = accounts.signInError {
                SettingsFailure(text: "Signing in failed: \(error)")
            }
        }
        .task { try? await accounts.loadClaude() }
        .confirmationDialog(
            "Sign out of Claude?", isPresented: $confirmingSignOut, titleVisibility: .visible
        ) {
            Button("Sign out", role: .destructive) {
                shell.settingsChange("Could not sign out") { try await accounts.signOut() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Claude Code on this Mac signs out too. Chats cannot run until you sign in again.")
        }
    }
}

/// Codex's ChatGPT sign-in through its app-server (B94): Sign in opens Codex's own page
/// in the browser, and the row waits until the daemon says how it went.
private struct CodexSection: View {
    @Environment(Shell.self) private var shell
    @State private var confirmingSignOut = false

    var body: some View {
        let accounts = shell.model.accounts
        let login = accounts.codex
        SettingsSection(title: "Codex", bare: true) {
            SettingsListRow(title: AccountText.codexTitle(login), detail: login?.plan) {
                OpenAIMark(size: 18)
                    .foregroundStyle(Palette.t2)
                    .frame(width: 26, height: 26)
                    .background(Palette.soft, in: .rounded(6))
            } trailing: {
                if let login {
                    StatusLabel(
                        tone: login.signedIn == true ? .review : .done,
                        label: AccountText.codexState(login), hollow: login.signedIn != true)
                }
                if accounts.isSigningInCodex {
                    Fireflies()
                    Text("Finish in the browser")
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                    Button("Cancel") {
                        shell.settingsChange("Could not cancel signing in") {
                            try await accounts.cancelCodexSignIn()
                        }
                    }
                    .buttonStyle(.nest(.soft))
                } else if login?.signedIn == true {
                    Button("Sign out") { confirmingSignOut = true }
                        .buttonStyle(.nest(.soft))
                        .disabled(accounts.isSigningOutCodex)
                } else if login != nil {
                    Button("Sign in") {
                        shell.settingsChange("Could not start signing in to Codex") {
                            NSWorkspace.shared.open(try await accounts.signInCodex())
                        }
                    }
                    .buttonStyle(.nest(.primary))
                }
            }
            .overlay(alignment: .top) { Separator() }
            if let error = accounts.codexSignInError {
                SettingsFailure(text: "Signing in failed: \(error)")
            }
        }
        .task { try? await accounts.loadCodex() }
        .confirmationDialog(
            "Sign out of Codex?", isPresented: $confirmingSignOut, titleVisibility: .visible
        ) {
            Button("Sign out", role: .destructive) {
                shell.settingsChange("Could not sign out of Codex") {
                    try await accounts.signOutCodex()
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Codex on this Mac signs out too. Codex chats cannot run until you sign in again.")
        }
    }
}

private struct GitHubSection: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let accounts = shell.model.accounts
        let github = accounts.github
        SettingsSection(title: "GitHub", bare: true) {
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
