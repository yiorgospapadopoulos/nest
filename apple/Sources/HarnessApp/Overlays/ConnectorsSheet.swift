import AppKit
import HarnessKit
import SwiftUI

/// The MCP servers and claude.ai connectors Claude Code reported, with their status and
/// where to set them up; harness cannot sign in on the user's behalf.
struct ConnectorsSheet: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let sections = shell.model.connectors.sections
        SheetFrame(title: "Connectors") {
            Text(
                "These come from your Claude Code setup. Agents in harness can use the connected ones."
            )
            .font(.ui(TypeSize.callout))
            .foregroundStyle(Palette.t2)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.top, 12)
            if sections.isEmpty {
                Text(
                    "Claude Code has not reported any yet. They appear after an agent's first turn."
                )
                .font(.ui(TypeSize.small))
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
                        .font(.system(size: 9, weight: .bold))
                        .rotationEffect(.degrees(open ? 0 : -90))
                    Text(section.title.uppercased()).tracking(0.66)
                    if let attention = section.attention {
                        Label(attention, systemImage: Icon.warning)
                            .labelStyle(TightLabelStyle())
                            .foregroundStyle(StatusTone.waiting.textColor)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    Text("\(section.connectors.count)").fontWeight(.semibold).monospacedDigit()
                }
                .font(.ui(TypeSize.caption, .bold))
                .foregroundStyle(Palette.t3)
                .padding(.top, 18)
                .padding(.bottom, 6)
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

    var body: some View {
        let state = connector.state
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 10) {
                Text(String(connector.displayName.prefix(1)).uppercased())
                    .font(.ui(TypeSize.caption, .bold))
                    .foregroundStyle(Palette.t2)
                    .frame(width: 26, height: 26)
                    .background(Palette.fill2, in: RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading, spacing: 1) {
                    Text(connector.displayName).font(.ui(TypeSize.body)).lineLimit(1)
                    if state == .failed, let error = connector.error {
                        Text(error)
                            .font(.ui(TypeSize.caption))
                            .foregroundStyle(StatusTone.failed.textColor)
                            .lineLimit(2)
                    }
                }
                Spacer(minLength: 8)
                StatusPill(tone: state.tone, label: state.label, hollow: false)
                if state != .connected {
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
                    "Run /mcp in Claude Code to set up \(connector.displayName); harness picks it up on the next turn."
                )
                .font(.ui(TypeSize.caption))
                .foregroundStyle(Palette.t3)
                .padding(.leading, 36)
                .transition(.opacity)
            }
        }
        .padding(.vertical, 9)
        .overlay(alignment: .top) {
            if !first {
                Rectangle().fill(Palette.hair).frame(height: 1)
            }
        }
    }
}
