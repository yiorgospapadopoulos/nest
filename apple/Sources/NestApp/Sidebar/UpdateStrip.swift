import NestKit
import SwiftUI

extension View {
    /// Pins the update strip to the bottom of a left bar's list, over it: rows scroll behind
    /// the strip, whose height becomes the list's bottom inset. The strip reads the updates
    /// itself, so the list does not observe them. `gap` is the bar's padding under the list,
    /// which the strip reaches across to sit on the status bar.
    func updateStrip(gap: Double) -> some View {
        safeAreaInset(edge: .bottom, spacing: 0) { UpdateStripView(gap: gap) }
    }

    /// The confirmation of a Relaunch or Undo update. The strip stays underneath an open
    /// Settings, so `inSettings` says which of the two asks.
    func updateRestartAlert(_ kind: UpdateRestart, inSettings: Bool = false) -> some View {
        modifier(UpdateRestartAlert(kind: kind, inSettings: inSettings))
    }
}

private struct UpdateStripView: View {
    let gap: Double
    @Environment(Shell.self) private var shell

    var body: some View {
        if let strip = shell.updates.strip {
            Group {
                switch strip {
                case .notice(let text):
                    NoticeStrip(text: text)
                case .ready(let engines, let relaunching):
                    ReadyStrip(engines: engines, relaunching: relaunching)
                }
            }
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t1)
            .padding(EdgeInsets(top: 6, leading: 10, bottom: 6, trailing: 6))
            .frame(maxWidth: .infinity, alignment: .leading)
            .background { UpdateCover() }
            .overlay(alignment: .top) { Separator() }
            .contentShape(Rectangle())
            .padding(.bottom, -gap)
        }
    }
}

/// Hides the rows behind it: the side surface, which lets them through, on the solid tint.
private struct UpdateCover: View {
    var body: some View {
        Palette.side.background(Palette.windowOpaque)
    }
}

private struct NoticeStrip: View {
    let text: String
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text(text)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 3)
            Button {
                shell.dismissUpdateNotice()
            } label: {
                Image(systemName: Icon.close).font(.system(size: 9, weight: .medium))
            }
            .buttonStyle(.nest(.plain, height: 20, iconOnly: true))
            .help("Dismiss")
            .accessibilityLabel("Dismiss")
        }
    }
}

private struct ReadyStrip: View {
    let engines: [EngineUpdate]
    let relaunching: Bool
    @Environment(Shell.self) private var shell
    @State private var open = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if open, !engines.isEmpty {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(engines) { engine in
                        Text(engine.change).monospacedDigit()
                    }
                }
                .padding(.top, 2)
            }
            // The narrowest bar wraps them.
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 4) {
                    relaunch
                    toggle
                    Spacer(minLength: 0)
                    hide
                }
                VStack(alignment: .leading, spacing: 4) {
                    relaunch
                    HStack(spacing: 4) {
                        toggle
                        Spacer(minLength: 0)
                        hide
                    }
                }
            }
        }
        .updateRestartAlert(.relaunch)
    }

    private var toggle: some View {
        Button {
            open.toggle()
        } label: {
            Image(systemName: Icon.chevron)
                .font(.system(size: 8, weight: .semibold))
                .rotationEffect(.degrees(open ? 0 : -90))
        }
        .buttonStyle(.nest(.plain, height: 20, iconOnly: true))
        .help("What's updating")
        .accessibilityLabel("What's updating")
        .accessibilityValue(open ? "Expanded" : "Collapsed")
    }

    private var hide: some View {
        Button {
            shell.updates.hideStrip()
        } label: {
            Image(systemName: Icon.close).font(.system(size: 9, weight: .medium))
        }
        .buttonStyle(.nest(.plain, height: 20, iconOnly: true))
        .disabled(relaunching)
        .help("Hide for now")
        .accessibilityLabel("Hide for now")
    }

    private var relaunch: some View {
        // Small enough to share the row at the standard width.
        Button {
            shell.startRestart(.relaunch)
        } label: {
            Text(relaunching ? "Relaunching..." : "Relaunch to update")
                .font(.ui(TypeSize.meta, .medium))
        }
        .buttonStyle(.nest(.primary, sidePadding: 6))
        .disabled(relaunching)
    }
}

private struct UpdateRestartAlert: ViewModifier {
    let kind: UpdateRestart
    let inSettings: Bool
    @Environment(Shell.self) private var shell

    func body(content: Content) -> some View {
        let asks = shell.settingsOpen == inSettings
        let question = shell.updates.asking.flatMap { asks && $0.kind == kind ? $0 : nil }
        content.alert(
            question?.title ?? "",
            isPresented: Binding(
                get: { question != nil },
                set: { if !$0 { shell.updates.cancel() } }),
            presenting: question
        ) { question in
            Button(question.action) { shell.confirmRestart(question.kind) }
            Button("Cancel", role: .cancel) {}
        } message: { question in
            Text(question.about)
        }
    }
}

/// The squeezed bar's sign of the strip; a click on the rail opens the bar.
struct UpdateRailDot: View {
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        if let strip = shell.updates.strip {
            Circle().fill(accent.accent).frame(width: 8, height: 8)
                .frame(maxWidth: .infinity)
                .frame(height: 20)
                .background { UpdateCover() }
                .help(Self.help(strip))
                .accessibilityLabel(Self.help(strip))
        }
    }

    private static func help(_ strip: UpdateStrip) -> String {
        if case .notice(let text) = strip {
            return text
        }
        return "Update available"
    }
}
