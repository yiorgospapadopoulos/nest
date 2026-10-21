import NestKit
import SwiftUI

/// The top of the sidebar: the project's icon and name, opening its local app actions,
/// with its current branch (or Init for a plain folder) beside it (B73: the bar over the
/// project is gone; B83: the squeeze button moved to the footer). The branch opens the
/// branch map, marked Live while it follows changes (B96).
struct ProjectHeader: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let project = shell.project ?? ""
        HStack(spacing: 8) {
            ProjectMenu().layoutPriority(2)
            switch shell.repo?.badge {
            case .branch(let branch):
                BranchLabel(project: project, branch: branch).layoutPriority(1)
            case .initGit: InitGitButton()
            case nil: EmptyView()
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

/// The current branch, small and grey after the project's name; it opens and closes the
/// branch map, tinted in the branch's lane colour while the map is open (B96).
private struct BranchLabel: View {
    let project: String
    let branch: String
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let open = shell.branchMaps.isOpen(project)
        let lane = shell.branchMaps.color(of: branch, in: project).map(Color.init)
        Button {
            withAnimation(reduceMotion ? nil : .smooth(duration: 0.25)) {
                shell.branchMaps.toggle(project)
            }
        } label: {
            HoverReader { hovering in
                HStack(spacing: 5) {
                    Image(systemName: Icon.branch).font(.system(size: 9.5))
                    Text(branch).lineLimit(1).truncationMode(.middle)
                    Image(systemName: open ? Icon.chevronUp : Icon.chevron)
                        .font(.system(size: 7, weight: .semibold))
                        .opacity(open || hovering ? 1 : 0.6)
                }
                .font(.ui(TypeSize.meta))
                .foregroundStyle(open ? lane ?? Palette.t1 : hovering ? Palette.t2 : Palette.t3)
                .padding(.horizontal, 7)
                .frame(height: 20)
                .background(
                    open ? (lane ?? Palette.t1).opacity(0.16) : hovering ? Palette.soft : .clear,
                    in: .rounded(Radius.button)
                )
                .contentShape(Rectangle())
            }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .padding(.leading, -7)
        .help(open ? "Hide the branch map" : "Show the branch map")
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
                    Image(systemName: Icon.branch).font(.system(size: 9.5))
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

/// The project's icon and name, opening its local app actions.
private struct ProjectMenu: View {
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        Menu {
            Button {
                shell.newTerminal()
            } label: {
                Label("New terminal", systemImage: Icon.terminal)
            }
            Button {
                shell.newBrowser()
            } label: {
                Label("New browser", systemImage: Icon.globe)
            }
            Divider()
            Button {
                shell.openProject(in: .vscode)
            } label: {
                Label("Open in VS Code", systemImage: Icon.code)
            }
            .shortcut(.openInVSCode, shell)
            Button {
                shell.openProject(in: .finder)
            } label: {
                Label("Reveal in Finder", systemImage: Icon.folder)
            }
            Button {
                shell.openProject(in: .terminal)
            } label: {
                Label("Open in Terminal", systemImage: Icon.terminal)
            }
            Divider()
            Button {
                shell.copyProjectPath()
            } label: {
                Label("Copy path", systemImage: Icon.copy)
            }
            Divider()
            Button {
                if let project = shell.project {
                    shell.openSettings(.project(project))
                }
            } label: {
                Label("Project settings…", systemImage: Icon.gear)
            }
        } label: {
            let project = shell.project ?? ""
            HStack(spacing: 8) {
                ProjectIcon(project: project, repo: shell.app.repo(project), size: 15)
                Text(project)
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
        .accessibilityLabel("Project \(shell.project ?? "")")
    }
}
