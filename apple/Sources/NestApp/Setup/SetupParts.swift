import AppKit
import NestKit
import SwiftUI

/// A step's round mark: filled with a check, a hollow ring, a ring with a dot, a dashed ring.
struct StepMark: View {
    let mark: SetupMark

    var body: some View {
        ZStack {
            switch mark {
            case .ok:
                Circle().fill(StatusTone.review.color)
                Image(systemName: Icon.check)
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(Palette.windowOpaque)
            case .todo:
                Circle().strokeBorder(Palette.t2.opacity(0.6), lineWidth: 1.5)
            case .now:
                Circle().strokeBorder(StatusTone.waiting.color, lineWidth: 1.5)
                Circle().fill(StatusTone.waiting.color).frame(width: 6, height: 6)
            case .skipped:
                Circle().strokeBorder(
                    Palette.t2.opacity(0.7), style: StrokeStyle(lineWidth: 1.5, dash: [2.4, 2.4]))
            }
        }
        .frame(width: 14, height: 14)
        .accessibilityElement()
        .accessibilityLabel(mark.name)
    }
}

/// A mark and its line.
struct MarkLine: View {
    let mark: SetupMark
    let text: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            StepMark(mark: mark).alignmentGuide(.firstTextBaseline) { $0[.bottom] - 3 }
            Text(text)
                .font(.ui(TypeSize.reading))
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
    }
}

/// A line of secondary text on a page.
struct SetupLine: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.reading))
            .foregroundStyle(Palette.t2)
            .lineSpacing(3)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
    }
}

/// Copy, saying so for a moment.
struct CopyButton: View {
    let text: String
    var kind = NestButtonStyle.Kind.soft
    var height = Metrics.buttonHeight
    @Environment(Shell.self) private var shell
    @State private var copied = false

    var body: some View {
        Button(copied ? "Copied" : "Copy") {
            shell.copyText(text)
            copied = true
        }
        .buttonStyle(.nest(kind, height: height))
        .task(id: copied) {
            guard copied else { return }
            try? await Task.sleep(for: .seconds(1.5))
            copied = false
        }
    }
}

/// One line to paste, with Copy inside its box.
struct CopyableCommand: View {
    let command: String

    var body: some View {
        HStack(spacing: 12) {
            Text(command)
                .font(.mono(TypeSize.small))
                .foregroundStyle(Palette.t1)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
            CopyButton(text: command)
        }
        .padding(.leading, 12)
        .padding(.trailing, 8)
        .padding(.vertical, 8)
        .background(Palette.soft, in: .rounded(7))
        .overlay(RoundedRectangle.rounded(7).strokeBorder(Palette.divider))
    }
}

/// A check's way out: the command to paste, or the page to open.
struct FixAction: View {
    let fix: SetupCheck.Fix

    var body: some View {
        switch fix.kind {
        case .command:
            CopyableCommand(command: fix.value)
        case .link:
            Button("Open") {
                if let url = URL(string: fix.value) {
                    NSWorkspace.shared.open(url)
                }
            }
            .buttonStyle(.nest(.soft))
        case .unknown:
            EmptyView()
        }
    }
}

struct CheckAgain: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.setup
        HStack(spacing: 8) {
            Button("Check again") { shell.recheckSetup() }
                .buttonStyle(.nest(.soft))
                .disabled(store.checking)
            if store.checking {
                Fireflies()
            }
        }
    }
}

extension Shell {
    /// The daemon's checks and the system's answers, read again.
    func recheckSetup() {
        Task {
            await permissions.refresh()
            await model.setup.refresh()
        }
    }
}
