import HarnessKit
import SwiftUI

/// The Pixies tab: the pixie list and the selected pixie's page, or the starters while
/// there are none (D057).
struct PixiesView: View {
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        Group {
            if let pixie = shell.shownPixie {
                HStack(spacing: glass.spacing.gap) {
                    PixieList()
                    PixiePage(pixie: pixie)
                }
            } else if shell.pixies.pixies.isEmpty {
                NoPixiesView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                AllHiddenView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .padding(glass.spacing.gap)
    }
}

/// Every pixie is hidden: a way to list them again, to open and show them.
private struct AllHiddenView: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "eye.slash").font(.system(size: 22)).foregroundStyle(Palette.t2)
            Text("All pixies are hidden")
                .font(.ui(TypeSize.subhead, .semibold))
                .foregroundStyle(Palette.t1)
            HStack(spacing: 8) {
                Button("Show hidden") { shell.showsHiddenPixies = true }
                    .buttonStyle(.harness(height: 30))
                Button {
                    shell.createPixie(CreatePixieRequest(name: "New pixie"), details: true)
                } label: {
                    Label("New pixie", systemImage: Icon.plus)
                }
                .buttonStyle(.harness(.primary, height: 30))
            }
            .padding(.top, 4)
        }
    }
}

/// "Create your first pixie", with New pixie and the Reviewer and Tester starters.
private struct NoPixiesView: View {
    @Environment(Shell.self) private var shell
    @Environment(\.glass) private var glass

    var body: some View {
        VStack(spacing: 0) {
            SpriteView(mascot: .invader, color: PixieColor.standard, size: 96)
                .padding(.bottom, 18)
            Text("Create your first pixie")
                .font(.ui(TypeSize.headline, .bold))
                .foregroundStyle(Palette.t1)
            Text("A pixie is an agent you keep: its own soul, memory and one ongoing chat.")
                .font(.ui(TypeSize.callout))
                .foregroundStyle(Palette.t2)
                .multilineTextAlignment(.center)
                .padding(.top, 6)
            Button {
                shell.createPixie(CreatePixieRequest(name: "New pixie"), details: true)
            } label: {
                Label("New pixie", systemImage: Icon.plus)
            }
            .buttonStyle(.harness(.primary, height: 32))
            .padding(.top, 20)
            Text("Or start from a template")
                .font(.ui(TypeSize.small))
                .foregroundStyle(Palette.t3)
                .padding(.top, 18)
            HStack(spacing: 8) {
                ForEach(PixieTemplate.all, id: \.name) { template in
                    Button {
                        shell.createPixie(template.request, details: false)
                    } label: {
                        HStack(spacing: 8) {
                            SpriteView(
                                mascot: template.mascot, color: PixieColor.standard, size: 20)
                            Text(template.name)
                        }
                    }
                    .buttonStyle(.harness(height: 32))
                    .help("A \(template.name.lowercased()) with a starter soul")
                }
            }
            .padding(.top, 8)
        }
        .padding(EdgeInsets(top: 32, leading: 40, bottom: 32, trailing: 40))
        .frame(width: 440)
        .panelGlass(radius: glass.sheetRadius)
    }
}
