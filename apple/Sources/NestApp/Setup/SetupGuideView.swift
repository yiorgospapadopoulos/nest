import AppKit
import NestKit
import SwiftUI

/// The setup guide over the whole window (B130, design B): the steps on the left, every one
/// can be clicked, and one page at a time.
struct SetupGuideView: View {
    let flow: SetupFlow
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 0) {
            SetupRail(flow: flow)
                .frame(width: 232)
                .background { Palette.side.background(Palette.windowOpaque) }
            Separator(axis: .vertical)
            SetupPane(flow: flow).background(Palette.windowOpaque)
        }
        .foregroundStyle(Palette.t1)
        .ignoresSafeArea()
        .task { shell.recheckSetup() }
        .onReceive(
            NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)
        ) { _ in shell.recheckSetup() }
        .overlay {
            // Only a guide opened from Settings can be left this way.
            if !flow.firstRun {
                Button("Close") { shell.closeGuide() }
                    .keyboardShortcut(.cancelAction)
                    .opacity(0)
                    .frame(width: 0, height: 0)
                    .accessibilityHidden(true)
            }
        }
    }
}

private struct SetupRail: View {
    let flow: SetupFlow
    @Environment(Shell.self) private var shell

    var body: some View {
        let checks = shell.setupChecks ?? []
        let engineReady = shell.setupEngineReady
        VStack(alignment: .leading, spacing: 0) {
            Text("Set up Nest")
                .font(.ui(13, .semibold))
                .padding(.horizontal, 8)
                .padding(.bottom, 16)
                .accessibilityAddTraits(.isHeader)
            ForEach(SetupStep.allCases) { step in
                let open = step == flow.step
                Button {
                    flow.open(step)
                } label: {
                    HStack(spacing: 8) {
                        StepMark(
                            mark: SetupMark(
                                step == .engine && engineReady
                                    ? .ok : checks.first { $0.id == step.id }?.state,
                                open: open, skipped: flow.skipped.contains(step)))
                        Text(step.rail).font(.ui(13, open ? .medium : .regular))
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 8)
                    .frame(height: 32)
                    .contentShape(Rectangle())
                    .listRow(selected: open, radius: 7)
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .accessibilityAddTraits(open ? .isSelected : [])
            }
            Spacer(minLength: 0)
        }
        // Under the window's buttons.
        .padding(.top, 44)
        .padding(.horizontal, 8)
        .frame(maxHeight: .infinity, alignment: .top)
    }
}

/// The title, the page and the way on.
private struct SetupPane: View {
    let flow: SetupFlow
    @Environment(Shell.self) private var shell

    var body: some View {
        let step = flow.step
        let engineReady = shell.setupEngineReady
        VStack(alignment: .leading, spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text(step.title)
                        .font(.ui(24, .semibold))
                        .padding(.bottom, step.subtitle == nil ? 24 : 8)
                        .accessibilityAddTraits(.isHeader)
                    if let subtitle = step.subtitle {
                        SetupLine(text: subtitle).padding(.bottom, 24)
                    }
                    SetupPage(flow: flow, engineReady: engineReady)
                        .frame(maxWidth: 480, alignment: .leading)
                        .id(step)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 48)
                .padding(.horizontal, 56)
                .padding(.bottom, 16)
            }
            .scrollIndicators(.automatic)
            HStack(spacing: 8) {
                Spacer(minLength: 0)
                if step.canSkip {
                    Button("Skip") { flow.skip() }.buttonStyle(.nest(.plain, height: 30))
                }
                if !flow.isFirst {
                    Button("Back") { flow.back() }.buttonStyle(.nest(.soft, height: 30))
                }
                if flow.isLast {
                    Button("Finish") { shell.finishGuide() }
                        .buttonStyle(.nest(.primary, height: 30))
                        .disabled(!flow.canFinish(engineReady: engineReady))
                } else {
                    Button("Continue") { flow.moveOn(engineReady: engineReady) }
                        .buttonStyle(.nest(.primary, height: 30))
                        .disabled(!flow.canContinue(engineReady: engineReady))
                }
            }
            .padding(.horizontal, 56)
            .padding(.bottom, 24)
        }
    }
}
