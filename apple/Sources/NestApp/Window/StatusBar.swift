import AppKit
import NestKit
import SwiftUI

/// MonoCode's content colour at an opacity, the way its footer, composer and usage chip
/// are drawn: #ebebeb in dark, #2e2e2e in light.
enum Ink {
    static func content(_ opacity: Double) -> Color {
        Color(
            nsColor: NSColor(name: nil) { @Sendable appearance in
                let dark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
                let level = dark ? 0xEB / 255.0 : 0x2E / 255.0
                return NSColor(srgbRed: level, green: level, blue: level, alpha: opacity)
            })
    }
}

/// The bar along the bottom of the window (MonoCode's footer): 28 points, no fill of its
/// own, a 1 point line on top. On the left, Settings (as Cmd-comma). Where a project is
/// open, the Workspace / Board / Artifacts switch sits in the middle (B79; the Pixies tab
/// has Workspace / Artifacts), and on the right the Terminal button opens a terminal where
/// the focused chat works, else the project's terminal pane, or a new one in the project
/// folder, followed by the activity panel's toggle, under the panel (B73). MonoCode shows
/// a running command's chip there instead; the terminal panes do not report their
/// foreground process, so it is left out. A maximized pane is restored from its header.
struct StatusBar: View {
    static let height = 28.0

    @Environment(Shell.self) private var shell

    private var inProject: Bool { shell.project != nil && !shell.pixiesOpen }
    private var hasViews: Bool { inProject || shell.pixiesOpen && !shell.pixies.pixies.isEmpty }

    var body: some View {
        HStack(spacing: 6) {
            Button {
                shell.show(.settings)
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: Icon.gear).font(.system(size: 11))
                    Text("Settings")
                }
            }
            .buttonStyle(FooterButtonStyle())
            .help("Settings (⌘,)")
            .accessibilityLabel("Settings")
            Spacer(minLength: 0)
            if inProject {
                Button {
                    shell.openProjectTerminal()
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: Icon.terminal).font(.system(size: 11))
                        Text("Terminal")
                    }
                }
                .buttonStyle(FooterButtonStyle())
                .help("Open a terminal where the focused chat works")
                .accessibilityLabel("Terminal")
                let collapsed = shell.projectState.rightCollapsed
                Button {
                    shell.update { $0.rightCollapsed.toggle() }
                } label: {
                    Image(systemName: Icon.rightPanel).font(.system(size: 11))
                }
                .buttonStyle(FooterButtonStyle(selected: !collapsed))
                .help("Activity panel")
                .accessibilityLabel("Activity panel")
                .accessibilityAddTraits(collapsed ? [] : .isSelected)
            }
        }
        .overlay {
            if hasViews {
                ViewSwitch(
                    views: ProjectView.choices(pixies: shell.pixiesOpen),
                    view: shell.workspaceState.view, unseen: shell.artifacts.unseen
                ) { shell.showView($0) }
            }
        }
        .font(.ui(11))
        .foregroundStyle(Ink.content(0.55))
        .padding(.horizontal, 12)
        .frame(height: Self.height)
        .frame(maxWidth: .infinity)
        .overlay(alignment: .top) {
            Rectangle().fill(Ink.content(0.07)).frame(height: 1)
        }
    }
}

/// The middle of the footer: the views as footer buttons; the selected one stays at full
/// strength over the accent's selection fill. Artifacts carries the count of artifacts
/// not opened yet, hidden at 0.
private struct ViewSwitch: View {
    let views: [ProjectView]
    let view: ProjectView
    let unseen: Int
    let select: (ProjectView) -> Void

    var body: some View {
        HStack(spacing: 2) {
            ForEach(views, id: \.self) { value in
                let selected = view == value
                Button {
                    select(value)
                } label: {
                    HStack(spacing: 5) {
                        Text(value.title)
                        if value == .artifacts, let badge = ArtifactText.badge(unseen) {
                            UnseenBadge(text: badge)
                        }
                    }
                    .fixedSize()
                }
                .buttonStyle(FooterButtonStyle(selected: selected, accentFill: true))
                .accessibilityAddTraits(selected ? .isSelected : [])
                .accessibilityValue(
                    value == .artifacts && unseen > 0 ? "\(unseen) not opened" : "")
            }
        }
    }
}

/// A small count in the accent, such as the Artifacts view's unopened ones.
struct UnseenBadge: View {
    let text: String
    @Environment(\.accentColors) private var accent

    var body: some View {
        Text(text)
            .font(.system(size: 9, weight: .semibold))
            .monospacedDigit()
            .foregroundStyle(accent.onAccent)
            .padding(.horizontal, 4)
            .frame(minWidth: 14, minHeight: 14)
            .background(accent.accent, in: Capsule())
            .accessibilityHidden(true)
    }
}

/// The footer's buttons: 20 points tall, 4 point corners, text at 55 percent (full while
/// hovered, over a 10 percent fill). A selected one stays at full strength; with
/// `accentFill` it also keeps the accent's selection fill.
private struct FooterButtonStyle: ButtonStyle {
    var selected = false
    var accentFill = false
    @Environment(\.accentColors) private var accent

    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(Ink.content(hovering || selected ? 1 : 0.55))
                .padding(.horizontal, 6)
                .frame(height: 20)
                .background(
                    selected && accentFill
                        ? accent.selection
                        : hovering || configuration.isPressed ? Ink.content(0.1) : .clear,
                    in: .rounded(4)
                )
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}
