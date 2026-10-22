import AppKit
import NestKit
import SwiftUI

/// The first-run welcome (B106), while nothing is signed in, no local model is added and the
/// welcome was never answered: sign in to Claude or Codex, or use local models only, which
/// opens Add local model on Find on this Mac.
struct FirstRunView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(LocalModelText.welcomeTitle)
                .font(.ui(24, .semibold))
            Text(LocalModelText.welcomeBody)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(LocalModelText.firstRunChoices) { choice in
                FirstRunChoiceRow(choice: choice) { choose(choice.id) }
            }
        }
        .foregroundStyle(Palette.t1)
        .frame(width: 440)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.windowOpaque.opacity(0.6))
    }

    private func choose(_ kind: LocalModelText.FirstRunChoice.Kind) {
        let local = shell.model.local
        let accounts = shell.model.accounts
        shell.settingsChange("Could not continue") {
            switch kind {
            case .local:
                try await local.useLocalOnly()
                shell.openAddLocal()
            case .claude, .codex:
                try await local.finishSetup()
                shell.openSettings(.accounts)
                let engine = kind == .claude ? ProviderInfo.claude : EngineMark.codex
                if let account = accounts.accounts(of: engine).first,
                    let page = try await accounts.signIn(account.id)
                {
                    NSWorkspace.shared.open(page)
                }
            }
        }
    }
}

/// One way in: its mark, title and line, and a chevron.
private struct FirstRunChoiceRow: View {
    let choice: LocalModelText.FirstRunChoice
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                mark
                    .foregroundStyle(Palette.t1)
                    .frame(width: 30, height: 30)
                    .background(Palette.selection, in: .rounded(7))
                VStack(alignment: .leading, spacing: 1) {
                    Text(choice.title).font(.ui(TypeSize.ui, .semibold))
                    Text(choice.detail)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t2)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: Icon.chevronRight)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Palette.t3)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(Palette.soft, in: .rounded(9))
            .overlay(RoundedRectangle.rounded(9).strokeBorder(Palette.divider, lineWidth: 1))
            .contentShape(.rounded(9))
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
    }

    @ViewBuilder private var mark: some View {
        switch choice.id {
        case .claude: ClaudeMark(size: 15)
        case .codex: OpenAIMark(size: 15)
        case .local:
            Image(systemName: Icon.localModel).font(.system(size: 14, weight: .medium))
        }
    }
}
