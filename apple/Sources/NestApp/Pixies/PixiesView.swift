import NestKit
import SwiftUI

/// The Pixies tab: the pixie list, the workspace where pixies open as panes like chats
/// (B37) or the pixies' artifacts (B79), and the focused pixie's details on the right; or
/// the starters while there are no pixies (D072).
struct PixiesView: View {
    static let detailsWidth = 320.0
    @Environment(Shell.self) private var shell

    var body: some View {
        if shell.pixies.pixies.isEmpty {
            NoPixiesView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            HStack(spacing: 0) {
                PixieList()
                Separator(axis: .vertical)
                if shell.app.pixieState.view == .artifacts {
                    ArtifactsView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .paneSurface()
                } else {
                    WorkspaceView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .chatBackdrop()
                }
                if shell.pixieDetailsOpen, let pixie = shell.shownPixie {
                    HStack(spacing: 0) {
                        Separator(axis: .vertical)
                        PixieDetailsPanel(pixie: pixie)
                            .frame(width: Self.detailsWidth)
                            .frame(maxHeight: .infinity)
                            .sideSurface()
                    }
                    .transition(.move(edge: .trailing).combined(with: .opacity))
                }
            }
            // A pixie deleted elsewhere leaves the workspace.
            .onChange(of: shell.pixies.pixies.map(\.id), initial: true) {
                shell.keepPixiePanes()
            }
        }
    }
}

/// The Pixies tab's empty workspace: the listed pixies to open and New pixie, or, while
/// every pixie is hidden, a way to list them again.
struct NoPixiePanes: View {
    /// The pixies offered here; the list holds the rest.
    static let offered = 4
    @Environment(Shell.self) private var shell

    var body: some View {
        let listed = shell.listedPixies
        VStack(spacing: 10) {
            if listed.isEmpty {
                Image(systemName: "eye.slash").font(.system(size: 16)).foregroundStyle(Palette.t3)
                Text("All pixies are hidden")
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                HStack(spacing: 6) {
                    Button("Show hidden") { shell.showsHiddenPixies = true }
                        .buttonStyle(.nest())
                    NewPixieButton()
                }
                .padding(.top, 4)
            } else {
                Image(systemName: Icon.workspace)
                    .font(.system(size: 20, weight: .light))
                    .foregroundStyle(Palette.t3)
                Text("Open a pixie, or drag pixies here to chat with them side by side")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t2)
                    .multilineTextAlignment(.center)
                HStack(spacing: 6) {
                    ForEach(listed.prefix(Self.offered)) { pixie in
                        Button {
                            shell.openPixie(pixie.id)
                        } label: {
                            let working = shell.isWorking(pixie)
                            HStack(spacing: 8) {
                                SpriteView(
                                    mascot: pixie.mascot, color: pixie.color, size: 14,
                                    working: working, phaseKey: pixie.id)
                                Text(pixie.name)
                                StillWorkingDot(working: working)
                            }
                        }
                        .buttonStyle(.nest(height: 26))
                        .help("Open \(pixie.name)")
                    }
                }
                .padding(.top, 4)
                NewPixieButton()
            }
        }
        .padding(24)
    }
}

/// New pixie, which opens the new pixie's pane and its details to set it up.
private struct NewPixieButton: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        Button {
            shell.createPixie(CreatePixieRequest(name: "New pixie"), details: true)
        } label: {
            Label("New pixie", systemImage: Icon.plus)
        }
        .buttonStyle(.nest(.primary))
    }
}

/// "Create your first pixie", with New pixie and the Reviewer and Tester starters.
private struct NoPixiesView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 0) {
            SpriteView(mascot: .bluebell, color: PixieColor.standard, size: 64)
                .padding(.bottom, 16)
            Text("Create your first pixie")
                .font(.ui(TypeSize.body, .semibold))
                .foregroundStyle(Palette.t1)
            Text("A pixie is an agent you keep: its own soul, memory and one ongoing chat.")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .multilineTextAlignment(.center)
                .padding(.top, 6)
            Button {
                shell.createPixie(CreatePixieRequest(name: "New pixie"), details: true)
            } label: {
                Label("New pixie", systemImage: Icon.plus)
            }
            .buttonStyle(.nest(.primary, height: 26))
            .padding(.top, 16)
            Text("Or start from a template")
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .padding(.top, 16)
            HStack(spacing: 6) {
                ForEach(PixieTemplate.all, id: \.name) { template in
                    Button {
                        shell.createPixie(template.request, details: false)
                    } label: {
                        HStack(spacing: 8) {
                            SpriteView(
                                mascot: template.mascot, color: PixieColor.standard, size: 14)
                            Text(template.name)
                        }
                    }
                    .buttonStyle(.nest(height: 26))
                    .help("A \(template.name.lowercased()) with a starter soul")
                }
            }
            .padding(.top, 8)
        }
        .padding(EdgeInsets(top: 28, leading: 32, bottom: 28, trailing: 32))
        .frame(width: 400)
    }
}
