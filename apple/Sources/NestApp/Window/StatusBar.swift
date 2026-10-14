import AppKit
import NestKit
import SwiftUI

/// the approved design's content colour at an opacity, the way its footer, composer and usage chip
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

/// The bar along the bottom of the window (the approved design's footer): 28 points, no fill of its
/// own, a 1 point line on top. On the left, Settings (as Cmd-comma); on the right, where
/// a project is open, the Terminal button opens the project's terminal pane, or a new one
/// in the project folder. the approved design shows a running command's chip there instead; the
/// terminal panes do not report their foreground process, so it is left out.
struct StatusBar: View {
    static let height = 28.0

    @Environment(Shell.self) private var shell

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
            if shell.project != nil && !shell.pixiesOpen {
                Button {
                    shell.openProjectTerminal()
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: Icon.terminal).font(.system(size: 11))
                        Text("Terminal")
                    }
                }
                .buttonStyle(FooterButtonStyle())
                .help("Open the project's terminal")
                .accessibilityLabel("Terminal")
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

/// The footer's buttons: 20 points tall, 4 point corners, text at 55 percent (full while
/// hovered, over a 10 percent fill).
private struct FooterButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        HoverReader { hovering in
            configuration.label
                .foregroundStyle(Ink.content(hovering ? 1 : 0.55))
                .padding(.horizontal, 6)
                .frame(height: 20)
                .background(
                    hovering || configuration.isPressed ? Ink.content(0.1) : .clear,
                    in: .rounded(4)
                )
                .contentShape(Rectangle())
                .pointerStyle(.link)
        }
    }
}
