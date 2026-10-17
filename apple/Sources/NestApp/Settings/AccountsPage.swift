import NestKit
import SwiftUI

/// The Claude Code login, through Claude Code's own commands, and the `gh` login (B81).
struct AccountsPage: View {
    var body: some View {
        ClaudeSection()
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
                    ProgressView().controlSize(.small)
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
                    ProgressView().controlSize(.small)
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
