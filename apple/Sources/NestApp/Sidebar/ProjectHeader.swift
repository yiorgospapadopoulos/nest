import AppKit
import NestKit
import SwiftUI

/// The top of the sidebar: the project's icon and name, opening its local app actions,
/// with where new chats start (or Init for a plain folder) beside it (B73: the bar over the
/// project is gone; B83: the squeeze button moved to the footer). The branch opens the
/// branch map, marked Live while it follows changes (B96). It reads the selected place and
/// nothing an open chat reads, so open chats do not look as if they moved (B131).
struct ProjectHeader: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let project = shell.project ?? ""
        HStack(spacing: 8) {
            // The name gives way before the branch, which has its own cap.
            ProjectMenu().layoutPriority(1)
            if let repo = shell.repo, !repo.isGeneral {
                if !repo.git {
                    InitGitButton()
                } else if let branch = repo.startBranch(map: shell.branchMaps.map(project)) {
                    BranchLabel(
                        project: project, branch: branch, selected: repo.selectedPlace != nil
                    )
                    .layoutPriority(2)
                }
            }
            Spacer(minLength: 0)
            if shell.branchMaps.isOpen(project), shell.app.connection == .connected {
                LiveMark().padding(.trailing, 4)
            }
        }
        // Where it sat inside the bar's former 6 point inset (B93).
        .padding(.leading, 14)
        .padding(.trailing, 8)
        .frame(height: 30)
    }
}

/// Where new chats start, small and grey after the project's name, cut in the middle past
/// its cap; it opens and closes the branch map, tinted in the branch's lane colour while the
/// map is open (B96) or a place is selected (B131).
private struct BranchLabel: View {
    static let maxWidth = 102.0
    let project: String
    let branch: String
    let selected: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let open = shell.branchMaps.isOpen(project)
        let lane = shell.branchMaps.color(of: branch, in: project).map(Color.init)
        let tinted = open || selected
        Button {
            withAnimation(reduceMotion ? nil : .smooth(duration: 0.25)) {
                shell.branchMaps.toggle(project)
            }
            if shell.branchMaps.isOpen(project) {
                shell.app.reloadRepos()
            }
        } label: {
            HoverReader { hovering in
                WidthCap(maxWidth: Self.maxWidth - 14) {
                    HStack(spacing: 5) {
                        BranchIcon(size: 9.5)
                        Text(branch).lineLimit(1).truncationMode(.middle)
                        Image(systemName: open ? Icon.chevronUp : Icon.chevron)
                            .font(.system(size: 7, weight: .semibold))
                            .opacity(open || hovering ? 1 : 0.6)
                    }
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(tinted ? lane ?? Palette.t1 : hovering ? Palette.t2 : Palette.t3)
                .padding(.horizontal, 7)
                .frame(height: 20)
                .background(
                    tinted ? (lane ?? Palette.t1).opacity(0.16) : hovering ? Palette.soft : .clear,
                    in: .rounded(Radius.button)
                )
                .contentShape(Rectangle())
            }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .padding(.leading, -7)
        .help(branch)
        .accessibilityLabel("Branch \(branch), \(open ? "hide" : "show") branch map")
    }
}

/// A plain folder's place for the branch: starts a chat that sets it up with git.
private struct InitGitButton: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.setUpGit()
        } label: {
            HoverReader { hovering in
                HStack(spacing: 5) {
                    BranchIcon(size: 9.5)
                    Text("Init").font(.ui(TypeSize.meta))
                }
                .foregroundStyle(hovering ? Palette.t1 : Palette.t2)
                .padding(.horizontal, 7)
                .frame(height: 20)
                .background(
                    hovering ? Palette.selection : Palette.soft, in: .rounded(Radius.button)
                )
                .contentShape(Rectangle())
            }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help("Set this folder up as a git repository")
        .accessibilityLabel("Init: set this folder up as a git repository")
    }
}

/// Open in (B152): every installed editor, the default one with the shortcut, then the
/// Finder and Terminal.
private struct OpenInMenu: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let editors = shell.app.editors
        Menu {
            ForEach(editors.installed) { editor in
                if editor.id == editors.default {
                    button(editor.name, .editor(editor.id)).shortcut(.openInEditor, shell)
                } else {
                    button(editor.name, .editor(editor.id))
                }
            }
            if !editors.installed.isEmpty {
                Divider()
            }
            button("Finder", .finder)
            button("Terminal", .terminal)
        } label: {
            Label("Open in", systemImage: Icon.code)
        }
    }

    private func button(_ title: String, _ app: RepoApp) -> some View {
        Button(title) { shell.openProject(in: app) }
    }
}

/// The project's icon and name, opening its local app actions.
private struct ProjectMenu: View {
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        // General's folder belongs to Nest: no path to copy and no settings (B110).
        let general = shell.repo?.isGeneral == true
        Menu {
            if !general {
                Button {
                    shell.newTerminal()
                } label: {
                    Label("New terminal", systemImage: Icon.terminal)
                }
                .localOnly(shell, DaemonText.terminalOff)
            }
            Button {
                shell.newBrowser()
            } label: {
                Label("New browser", systemImage: Icon.globe)
            }
            Divider()
            OpenInMenu()
                .localOnly(shell, DaemonText.appsOff)
            Divider()
            if shell.isRemote {
                Text(DaemonText.appsOff(shell.machineName))
            }
            if !general {
                Button {
                    shell.copyProjectPath()
                } label: {
                    Label(
                        shell.isRemote ? DaemonText.copyPath(shell.machineName) : "Copy path",
                        systemImage: Icon.copy)
                }
                Divider()
                Button {
                    if let project = shell.project {
                        shell.openSettings(.project(project))
                    }
                } label: {
                    Label("Project settings…", systemImage: Icon.gear)
                }
            }
        } label: {
            let project = shell.project ?? ""
            HStack(spacing: 8) {
                ProjectIcon(project: project, repo: shell.app.repo(project), size: 15)
                Text(shell.repo?.title ?? project)
                    .font(.ui(TypeSize.reading, .semibold))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                Image(systemName: Icon.chevron)
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(Palette.t3)
            }
            .padding(.horizontal, 6)
            .frame(height: Metrics.buttonHeight)
            .background(hovering ? Palette.soft : .clear, in: .rounded(Radius.button))
            .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .menuIndicator(.hidden)
        .onHover { hovering = $0 }
        .padding(.leading, -6)
        .accessibilityLabel("Project \(shell.repo?.title ?? shell.project ?? "")")
        // An editor installed meanwhile shows in Open in.
        .onReceive(
            NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)
        ) { _ in Task { try? await shell.app.loadEditors() } }
    }
}
