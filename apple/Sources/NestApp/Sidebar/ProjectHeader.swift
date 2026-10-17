import NestKit
import SwiftUI

/// The top of the sidebar: the project's icon and name, opening its local app actions,
/// with its current branch (or Init for a plain folder) beside it, and the collapse
/// button (B73: the bar over the project is gone).
struct ProjectHeader: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        HStack(spacing: 8) {
            ProjectMenu().layoutPriority(1)
            switch shell.repo?.badge {
            case .branch(let branch): BranchLabel(branch: branch)
            case .initGit: InitGitButton()
            case nil: EmptyView()
            }
            Spacer(minLength: 0)
            Button {
                shell.update { $0.leftCollapsed = true }
            } label: {
                Image(systemName: Icon.leftPanel).font(.system(size: 13))
                    .foregroundStyle(Palette.t3)
            }
            .buttonStyle(.nest(.plain, iconOnly: true))
            .help("Collapse sidebar")
            .accessibilityLabel("Collapse sidebar")
        }
        .padding(.leading, 8)
        .padding(.trailing, 2)
        .frame(height: 30)
    }
}

/// The current branch, small and grey after the project's name.
private struct BranchLabel: View {
    let branch: String

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: Icon.branch).font(.system(size: 9.5))
            Text(branch).lineLimit(1).truncationMode(.middle)
        }
        .font(.ui(TypeSize.meta))
        .foregroundStyle(Palette.t3)
        .help(branch)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Branch \(branch)")
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
