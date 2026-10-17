import AppKit
import NestKit
import SwiftUI

/// The MCP servers and claude.ai connectors Claude Code reported, grouped, with their
/// status and where to set them up; Sign in opens Claude Code's `/mcp` in the terminal, or
/// claude.ai for its connectors (B59). Settings > Extensions > Connections (B81).
struct ConnectorsList: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let sections = shell.model.connectors.sections
        VStack(alignment: .leading, spacing: 0) {
            if sections.isEmpty {
                Text(
                    "Claude Code has not reported any yet. They appear after an agent's first turn."
                )
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 28)
            }
            ForEach(sections) { section in
                ConnectorGroup(section: section)
            }
        }
        .task { try? await shell.model.connectors.load() }
    }
}

/// A folding group of connectors: its title, count and any trouble, with the rows below
/// once it is unfolded.
private struct ConnectorGroup: View {
    let section: ConnectorSection
    @Environment(Shell.self) private var shell

    var body: some View {
        let open = shell.connectorGroupsOpen.contains(section.kind)
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.smooth(duration: 0.2)) {
                    if open {
                        shell.connectorGroupsOpen.remove(section.kind)
                    } else {
                        shell.connectorGroupsOpen.insert(section.kind)
                    }
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .semibold))
                        .rotationEffect(.degrees(open ? 0 : -90))
                    Text(section.title)
                    Text("\(section.connectors.count)").monospacedDigit()
                    if let attention = section.attention {
                        StatusLabel(tone: .waiting, label: attention)
                    }
                    Spacer(minLength: 8)
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.top, 14)
                .padding(.bottom, 2)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .accessibilityLabel(
                "\(section.title), \(section.connectors.count)\(section.attention.map { ", \($0)" } ?? "")"
            )
            .accessibilityValue(open ? "Expanded" : "Collapsed")
            if open {
                ForEach(Array(section.connectors.enumerated()), id: \.element.id) {
                    index, connector in
                    ConnectorRow(connector: connector, first: index == 0)
                }
            }
        }
    }
}

private struct ConnectorRow: View {
    let connector: Connector
    let first: Bool
    @State private var showsHint = false
    @Environment(Shell.self) private var shell

    var body: some View {
        let state = connector.state
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 10) {
                Text(String(connector.displayName.prefix(1)).uppercased())
                    .font(.ui(10, .semibold))
                    .foregroundStyle(Palette.t2)
                    .frame(width: 18, height: 18)
                    .background(Palette.soft, in: .rounded(Radius.chip))
                VStack(alignment: .leading, spacing: 1) {
                    Text(connector.displayName).font(.ui(TypeSize.ui)).lineLimit(1)
                    if state == .failed, let error = connector.error {
                        Text(error)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(StatusTone.failed.color)
                            .lineLimit(2)
                    }
                }
                Spacer(minLength: 8)
                StatusLabel(tone: state.tone, label: state.label, hollow: false)
                if connector.signIn != nil {
                    Button("Sign in") { shell.signIn(connector) }
                        .buttonStyle(LinkButtonStyle())
                        .help(
                            connector.managedOnClaudeAI
                                ? "Opens claude.ai's connector settings"
                                : "Runs claude /mcp in the terminal to sign in"
                        )
                        .accessibilityLabel("Sign in to \(connector.displayName)")
                } else if state != .connected {
                    Button(
                        connector.managedOnClaudeAI
                            ? "Sign in on claude.ai" : "Set up in Claude Code"
                    ) {
                        if connector.managedOnClaudeAI {
                            NSWorkspace.shared.open(ConnectorsStore.claudeAISettings)
                        } else {
                            withAnimation(.smooth(duration: 0.2)) { showsHint.toggle() }
                        }
                    }
                    .buttonStyle(LinkButtonStyle())
                    .accessibilityLabel(
                        "\(connector.managedOnClaudeAI ? "Sign in on claude.ai" : "Set up in Claude Code") for \(connector.displayName)"
                    )
                }
            }
            if showsHint {
                Text(
                    "Run /mcp in Claude Code to set up \(connector.displayName); Nest picks it up on the next turn."
                )
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.leading, 28)
                .transition(.opacity)
            }
        }
        .padding(.vertical, 7)
        .overlay(alignment: .top) {
            if !first {
                Separator()
            }
        }
    }
}
