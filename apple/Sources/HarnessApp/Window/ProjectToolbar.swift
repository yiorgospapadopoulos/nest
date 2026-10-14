import HarnessKit
import SwiftUI

/// The bar over the project: name menu, branch, view switch and activity panel toggle.
struct ProjectToolbar: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let state = shell.projectState
        HStack(spacing: 10) {
            ProjectMenu()
            switch shell.repo?.badge {
            case .branch(let branch): BranchLabel(branch: branch)
            case .initGit: InitGitButton()
            case nil: EmptyView()
            }
            ViewSwitch(view: state.view) { view in shell.update { $0.view = view } }
                .padding(.leading, 6)
            if state.layout.maximized != nil && state.view == .workspace {
                Button {
                    shell.update { $0.layout.restore() }
                } label: {
                    Label("Restore", systemImage: Icon.restore)
                }
                .buttonStyle(.harness(.plain))
            }
            Spacer()
            Button {
                shell.update { $0.rightCollapsed.toggle() }
            } label: {
                Image(systemName: Icon.rightPanel).font(.system(size: 13))
                    .foregroundStyle(state.rightCollapsed ? Palette.t3 : Palette.t2)
            }
            .buttonStyle(.harness(.plain, iconOnly: true))
            .help("Activity panel")
            .accessibilityLabel("Activity panel")
            .accessibilityAddTraits(state.rightCollapsed ? [] : .isSelected)
        }
        .padding(.leading, 14)
        .padding(.trailing, 8)
        .frame(height: Metrics.toolbarHeight)
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

/// The project name, opening its local app actions.
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
            .keyboardShortcut("o", modifiers: [.command, .shift])
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
                    shell.show(.project(project))
                }
            } label: {
                Label("Project settings…", systemImage: Icon.gear)
            }
        } label: {
            HStack(spacing: 5) {
                Text(shell.project ?? "")
                    .font(.ui(TypeSize.ui, .semibold))
                    .foregroundStyle(Palette.t1)
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
        .fixedSize()
        .onHover { hovering = $0 }
        .padding(.leading, -6)
        .accessibilityLabel("Project \(shell.project ?? "")")
    }
}

/// Workspace or Board.
private struct ViewSwitch: View {
    let view: ProjectView
    let select: (ProjectView) -> Void
    @Environment(\.accentColors) private var accent

    var body: some View {
        HStack(spacing: 2) {
            segment(.workspace, "Workspace")
            segment(.board, "Board")
        }
    }

    private func segment(_ value: ProjectView, _ title: String) -> some View {
        let selected = view == value
        return Button {
            select(value)
        } label: {
            HoverReader { hovering in
                Text(title)
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(selected ? Palette.t1 : Palette.t2)
                    .padding(.horizontal, 9)
                    .frame(height: Metrics.buttonHeight)
                    .background(
                        selected ? accent.selection : hovering ? Palette.soft : .clear,
                        in: .rounded(Radius.button)
                    )
                    .contentShape(Rectangle())
            }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
