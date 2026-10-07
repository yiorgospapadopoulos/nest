import HarnessKit
import SwiftUI

/// The bar over the project: name menu, branch, view switch and activity panel toggle.
struct ProjectToolbar: View {
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        let state = shell.projectState
        HStack(spacing: 10) {
            HStack(spacing: 8) {
                ProjectMenu()
                switch shell.repo?.badge {
                case .branch(let branch): Chip(icon: Icon.branch, text: branch)
                case .initGit: InitGitButton()
                case nil: EmptyView()
                }
            }
            ViewSwitch(view: state.view) { view in shell.update { $0.view = view } }
            if state.layout.maximized != nil && state.view == .workspace {
                Button {
                    shell.update { $0.layout.restore() }
                } label: {
                    Label("Restore", systemImage: Icon.restore)
                }
                .buttonStyle(.harness(height: 24))
            }
            Spacer()
            Button {
                shell.update { $0.rightCollapsed.toggle() }
            } label: {
                Image(systemName: Icon.rightPanel).font(.system(size: 14))
            }
            .buttonStyle(.harness(.ghost, iconOnly: true))
            .foregroundStyle(state.rightCollapsed ? Palette.t2 : Palette.t1)
            .help("Activity panel")
            .accessibilityLabel("Activity panel")
            .accessibilityAddTraits(state.rightCollapsed ? [] : .isSelected)
        }
        .padding(.leading, 6)
        .padding(.trailing, 2)
        .frame(height: glass.spacing.toolbarHeight)
    }
}

/// A plain folder's place for the branch: starts a chat that sets it up with git.
private struct InitGitButton: View {
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        Button {
            shell.setUpGit()
        } label: {
            HoverReader { hovering in
                HStack(spacing: 5) {
                    Image(systemName: Icon.branch).font(.system(size: 10, weight: .medium))
                    Text("Init").font(.ui(TypeSize.label))
                }
                .foregroundStyle(hovering ? Palette.t1 : Palette.t2)
                .padding(.horizontal, 8)
                .frame(height: 22)
                .background(
                    hovering ? Palette.fill2 : Palette.fill, in: glass.rounded(glass.radius.small)
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
        } label: {
            HStack(spacing: 5) {
                Text(shell.project ?? "")
                    .font(.ui(TypeSize.body, .bold))
                    .foregroundStyle(Palette.t1)
                Image(systemName: Icon.chevron)
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(Palette.t3)
            }
            .padding(.horizontal, 8)
            .frame(height: 28)
            .background(hovering ? Palette.fill : .clear, in: RoundedRectangle(cornerRadius: 8))
            .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .menuIndicator(.hidden)
        .fixedSize()
        .onHover { hovering = $0 }
        .padding(.leading, -8)
        .accessibilityLabel("Project \(shell.project ?? "")")
    }
}

/// Workspace or Board.
private struct ViewSwitch: View {
    let view: ProjectView
    let select: (ProjectView) -> Void
    @Environment(\.glass) private var glass

    var body: some View {
        HStack(spacing: 0) {
            segment(.workspace, "Workspace", Icon.workspace)
            segment(.board, "Board", Icon.board)
        }
        .padding(2)
        .background(Palette.fill, in: glass.rounded(glass.radius.small + 2))
    }

    private func segment(_ value: ProjectView, _ title: String, _ icon: String) -> some View {
        let selected = view == value
        return Button {
            select(value)
        } label: {
            HStack(spacing: 6) {
                Image(systemName: icon).font(.system(size: 12))
                Text(title)
            }
            .font(.ui(TypeSize.small, .semibold))
            .foregroundStyle(selected ? Palette.t1 : Palette.t2)
            .padding(.horizontal, 11)
            .frame(height: 26)
            .background {
                if selected {
                    glass.rounded(glass.radius.small)
                        .fill(glass.surface)
                        .shadow(color: glass.shadow, radius: 1.5, y: 1)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
