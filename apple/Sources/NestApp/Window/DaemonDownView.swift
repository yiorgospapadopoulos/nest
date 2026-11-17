import AppKit
import NestKit
import SwiftUI

/// The window while This Mac's daemon cannot be reached at launch (B130, screen Z): an
/// update's progress while one has the daemon down, else, once starting the service by itself
/// did not help, Set up Nest on a Mac that has no Nest yet, or the line that repairs the
/// install, and Try again.
struct DaemonDownView: View {
    @Environment(Shell.self) private var shell
    @Environment(AppController.self) private var controller

    var body: some View {
        Group {
            if case .updating(let update) = shell.daemonDown.screen {
                UpdatingNestView(update: update)
            } else if controller.setup.isOffered {
                FirstSetupView(setup: controller.setup)
            } else {
                RepairView()
            }
        }
        .foregroundStyle(Palette.t1)
        .frame(width: 520)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.windowOpaque)
        .ignoresSafeArea()
    }
}

private struct RepairView: View {
    @Environment(AppController.self) private var controller

    var body: some View {
        let service = controller.service
        let line = service.installCommand
        VStack(alignment: .leading, spacing: 0) {
            Text("Nest's background service isn't running")
                .font(.ui(24, .semibold))
                .padding(.bottom, 8)
                .accessibilityAddTraits(.isHeader)
            SetupLine(text: "Paste this in Terminal. Your chats stay.").padding(.bottom, 16)
            Text(line)
                .font(.mono(TypeSize.small))
                .lineSpacing(3)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
                .background(Palette.soft, in: .rounded(7))
                .overlay(RoundedRectangle.rounded(7).strokeBorder(Palette.divider))
                .padding(.bottom, 16)
            HStack(spacing: 8) {
                CopyButton(text: line, kind: .primary, height: 30)
                Button("Try again") { controller.startService() }
                    .buttonStyle(.nest(.soft, height: 30))
                    .disabled(service.state == .starting)
                if service.state == .starting {
                    Fireflies()
                }
            }
            if case .failed(let reason) = service.state {
                SettingsFailure(text: reason).padding(.top, 8)
            }
        }
    }
}

/// A downloaded Nest.app on a Mac with no Nest: one button runs the release's installer, with
/// its own lines as the progress, and the setup guide follows once the service answers.
private struct FirstSetupView: View {
    let setup: NestSetup
    @Environment(AppController.self) private var controller

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            switch setup.phase {
            case .ready where !setup.isInApplications:
                Heading(text: "Move Nest to Applications")
                SetupLine(text: "Drag Nest into your Applications folder, then open it from there.")
                    .padding(.bottom, 16)
                Button("Quit and show Applications") {
                    NSWorkspace.shared.open(URL(fileURLWithPath: "/Applications"))
                    NSApp.terminate(nil)
                }
                .buttonStyle(.nest(.primary, height: 30))
            case .ready:
                Heading(text: "Welcome to Nest")
                SetupLine(
                    text: "Nest runs a small service in the background on this Mac. Setting it"
                        + " up downloads it and takes a few minutes."
                )
                .padding(.bottom, 16)
                Button("Set up Nest") { controller.setUp() }
                    .buttonStyle(.nest(.primary, height: 30))
            case .running(let progress):
                Heading(text: "Setting up Nest...").padding(.bottom, 8)
                SetupChecklist(progress: progress)
            case .finished:
                Heading(text: "Opening Nest...").padding(.bottom, 8)
                SetupChecklist(progress: nil)
            case .failed(let reason):
                Heading(text: "Nest couldn't be set up")
                SetupLine(text: reason).padding(.bottom, 16)
                Button("Try again") { controller.setUp() }
                    .buttonStyle(.nest(.primary, height: 30))
                    .padding(.bottom, 24)
                SetupLine(text: "Or paste this in Terminal:").padding(.bottom, 8)
                CopyableCommand(command: setup.terminalLine)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The installer's steps, each ticked off when done, with a percentage on each and a thin bar
/// under the one under way. Nil once every step is done. Estimates move every second.
private struct SetupChecklist: View {
    let progress: SetupProgress?

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            VStack(alignment: .leading, spacing: 0) {
                ForEach(InstallStep.allCases, id: \.self) { step in
                    let mark = progress?.mark(of: step) ?? .ok
                    let percent = progress?.percent(of: step, at: context.date) ?? 100
                    SetupStepRow(step: step, mark: mark, percent: percent)
                }
            }
        }
    }
}

private struct SetupStepRow: View {
    let step: InstallStep
    let mark: SetupMark
    let percent: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 12) {
                StepMark(mark: mark)
                Text(step.title)
                    .font(.ui(TypeSize.reading))
                    .foregroundStyle(mark == .todo ? Palette.t3 : Palette.t1)
                Spacer(minLength: 12)
                Text("\(percent)%")
                    .font(.ui(TypeSize.small))
                    .monospacedDigit()
                    .foregroundStyle(mark == .todo ? Palette.t3 : Palette.t2)
            }
            if mark == .now {
                Capsule()
                    .fill(Palette.divider)
                    .frame(height: 3)
                    .overlay(alignment: .leading) {
                        GeometryReader { size in
                            Capsule()
                                .fill(Palette.t1)
                                .frame(width: size.size.width * Double(percent) / 100)
                        }
                    }
                    .padding(.leading, 26)
                    .animation(.easeOut(duration: 0.25), value: percent)
            }
        }
        .padding(.vertical, 8)
        .accessibilityElement(children: .combine)
        .accessibilityValue("\(percent)%")
    }
}

private struct Heading: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(24, .semibold))
            .padding(.bottom, 8)
            .accessibilityAddTraits(.isHeader)
    }
}

/// While the daemon is down for an update: never the repair line, as Nest sees to it. Looks
/// again every second, so the window moves on as soon as the daemon is back. One screen the
/// whole time (B130, fix 30b): the slow line's place is kept from the start, so nothing moves
/// when it appears.
private struct UpdatingNestView: View {
    let update: UpdateUnderWay
    @Environment(AppController.self) private var controller

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            VStack(alignment: .leading, spacing: 0) {
                Text("Updating Nest to \(update.toVersion)...")
                    .font(.ui(24, .semibold))
                    .padding(.bottom, 8)
                    .accessibilityAddTraits(.isHeader)
                Fireflies().padding(.top, 8)
                let slow = update.isSlow(at: context.date)
                SetupLine(text: "Taking longer than usual")
                    .padding(.top, 16)
                    .opacity(slow ? 1 : 0)
                    .accessibilityHidden(!slow)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                controller.followUpdate()
            }
        }
    }
}
