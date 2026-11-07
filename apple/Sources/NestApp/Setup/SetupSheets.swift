import AppKit
import NestKit
import SwiftUI

/// What Settings > General opens over Settings (B130).
enum SetupSheet: Equatable {
    case checks
    case report(SetupReport)
    case uninstall
}

struct SetupSheets: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        if let sheet = shell.setupSheet {
            ZStack {
                Palette.scrim
                    .ignoresSafeArea()
                    .onTapGesture { shell.setupSheet = nil }
                Group {
                    switch sheet {
                    case .checks: CheckNestSheet()
                    case .report(let report): BugReportSheet(report: report)
                    case .uninstall: UninstallSheet()
                    }
                }
                .padding(40)
                Button("Close") { shell.setupSheet = nil }
                    .keyboardShortcut(.cancelAction)
                    .opacity(0)
                    .frame(width: 0, height: 0)
                    .accessibilityHidden(true)
            }
        }
    }
}

/// A sheet's title, scrolling body and footer.
private struct SetupSheetFrame<Content: View, Footer: View>: View {
    let title: String
    var width = 560.0
    @ViewBuilder let content: () -> Content
    @ViewBuilder let footer: () -> Footer
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title)
                .font(.ui(TypeSize.body, .semibold))
                .padding(.bottom, 12)
                .accessibilityAddTraits(.isHeader)
            ScrollView {
                VStack(alignment: .leading, spacing: 0, content: content)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 520)
            HStack(spacing: 8) {
                Spacer(minLength: 0)
                footer()
                Button("Close") { shell.setupSheet = nil }.buttonStyle(.nest(.soft, height: 30))
            }
            .padding(.top, 14)
        }
        .foregroundStyle(Palette.t1)
        .padding(20)
        .frame(width: width)
        .sheetSurface()
    }
}

/// Every check with its message and fix, the same list `nest doctor` prints: one list, what
/// matters most on top.
private struct CheckNestSheet: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.setup
        let checks = shell.setupChecks.map(SetupCheck.ranked)
        SetupSheetFrame(title: "Check Nest") {
            if let checks {
                ForEach(checks) { CheckRow(check: $0) }
            } else if !store.checking {
                SetupLine(text: "The checks could not run.")
            }
        } footer: {
            if store.checking {
                Fireflies()
            }
            Button("Check again") { shell.recheckSetup() }
                .buttonStyle(.nest(.soft, height: 30))
                .disabled(store.checking)
        }
        .task { shell.recheckSetup() }
        .onReceive(
            NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)
        ) { _ in shell.recheckSetup() }
    }
}

private struct CheckRow: View {
    let check: SetupCheck

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                StepMark(mark: SetupMark(check.state))
                Text(check.title).font(.ui(TypeSize.ui, .medium))
                Spacer(minLength: 8)
                if let detail = check.detail {
                    Text(detail)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .textSelection(.enabled)
                }
            }
            if !check.message.isEmpty || check.fix != nil {
                VStack(alignment: .leading, spacing: 8) {
                    if !check.message.isEmpty {
                        SetupLine(text: check.message)
                    }
                    if let fix = check.fix {
                        FixAction(fix: fix)
                    }
                }
                .padding(.leading, 22)
            }
        }
        .padding(.vertical, 8)
        .overlay(alignment: .bottom) { Separator() }
    }
}

/// The report in full, before anything else: Nest sends nothing, the file is the user's.
private struct BugReportSheet: View {
    let report: SetupReport
    @Environment(Shell.self) private var shell

    var body: some View {
        let path = (report.path as NSString).abbreviatingWithTildeInPath
        SetupSheetFrame(title: "Bug report", width: 680) {
            SetupLine(text: "Nest sends nothing. Saved as \(path)").padding(.bottom, 10)
            Text(report.text)
                .font(.mono(TypeSize.meta))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(Palette.soft, in: .rounded(7))
        } footer: {
            CopyButton(text: report.text, height: 30)
            // A remote daemon's file is on its machine.
            if !shell.isRemote {
                Button("Show the file") { showFile() }
                    .buttonStyle(.nest(.soft, height: 30))
            }
            Button("Report on GitHub") { reportOnGitHub() }
                .buttonStyle(.nest(.primary, height: 30))
                .disabled(URL(string: report.issueURL) == nil)
        }
    }

    private func showFile() {
        NSWorkspace.shared.activateFileViewerSelecting([URL(filePath: report.path)])
    }

    /// The issue opens in the browser for the user to read and submit; too long a report is
    /// attached by hand, so its file shows too.
    private func reportOnGitHub() {
        guard let url = URL(string: report.issueURL) else { return }
        NSWorkspace.shared.open(url)
        if report.attachFile, !shell.isRemote {
            showFile()
        }
    }
}

/// Uninstall Nest's confirmation (B130), with the choice to delete chats, settings and secrets
/// too, off by default, saying which. `nest uninstall` runs in a session of its own, so it
/// outlives the app and the service, and the app quits.
private struct UninstallSheet: View {
    @Environment(AppController.self) private var controller
    @Environment(Shell.self) private var shell
    @State private var deleteData = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Uninstall Nest?")
                .font(.ui(TypeSize.body, .semibold))
                .padding(.bottom, 8)
                .accessibilityAddTraits(.isHeader)
            SetupLine(
                text: deleteData
                    ? "Nest, its background service, and your chats, settings and secrets are"
                        + " deleted."
                    : "Nest and its background service are removed. Your chats, settings and"
                        + " secrets stay."
            )
            .padding(.bottom, 14)
            HStack(spacing: 12) {
                Text("Also delete chats, settings and secrets").font(.ui(TypeSize.ui))
                Spacer(minLength: 8)
                Switch(isOn: deleteData) { deleteData.toggle() }
                    .accessibilityLabel("Also delete chats, settings and secrets")
            }
            HStack(spacing: 8) {
                Spacer(minLength: 0)
                Button("Cancel") { shell.setupSheet = nil }
                    .buttonStyle(.nest(.soft, height: 30))
                Button("Uninstall") { uninstall() }
                    .buttonStyle(.nest(.destructive, height: 30))
            }
            .padding(.top, 18)
        }
        .foregroundStyle(Palette.t1)
        .padding(20)
        .frame(width: 420)
        .sheetSurface()
    }

    private func uninstall() {
        shell.setupSheet = nil
        if controller.install.uninstall(deleteData: deleteData, spawner: DetachedSpawner()) {
            NSApp.terminate(nil)
        } else {
            shell.show("Could not start the uninstall", kind: .failed)
        }
    }
}
