import AppKit
import NestKit
import SwiftUI

/// On the composer while the chat holds something (option A): the latest screenshot, the
/// app's name with a live dot, enlarge and Stop. A new screenshot is read on each frame.
struct ComputerStrip: View {
    let chat: String
    @Environment(Shell.self) private var shell
    @State private var enlarged = false

    var body: some View {
        let store = shell.model.computer
        let targets = store.targets(of: chat)
        if let target = shown(targets, frame: store.frame(of: chat)) {
            let name = target.name
            HStack(spacing: 10) {
                Button {
                    enlarged = true
                } label: {
                    ComputerThumbnail(png: store.image(of: chat), width: 96, height: 60)
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .accessibilityLabel("Screenshot of \(name)")
                Text(name)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(Palette.t1)
                    .lineLimit(1)
                StatusDot(tone: .running)
                Spacer(minLength: 4)
                Button {
                    enlarged = true
                } label: {
                    Image(systemName: Icon.maximize).font(.system(size: 10, weight: .medium))
                }
                .buttonStyle(.nest(.soft, height: 22, iconOnly: true))
                .help("Enlarge")
                .accessibilityLabel("Enlarge")
                Button {
                    shell.stopComputer(chat)
                } label: {
                    Label("Stop", systemImage: Icon.stop)
                }
                .buttonStyle(.nest(.danger, height: 22))
                .disabled(shell.sessions.settingComputer.contains(chat))
                .help("Stop using \(name)")
                .accessibilityLabel("Stop using \(name)")
            }
            .padding(.leading, 5)
            .padding(.trailing, 6)
            .padding(.vertical, 5)
            .background(Palette.soft, in: .rounded(12))
            .overlay(RoundedRectangle.rounded(12).strokeBorder(Palette.divider))
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Using \(name)")
            .task(id: store.frame(of: chat)?.seq) { await store.loadFrame(of: chat) }
            .popover(isPresented: $enlarged, arrowEdge: .top) {
                EnlargedFrame(chat: chat, name: name)
            }
            .transition(.opacity)
        }
    }

    /// The target the latest frame shows, else the first held.
    private func shown(_ targets: [ComputerTarget], frame: ComputerFrame?) -> ComputerTarget? {
        targets.first { $0.key == frame?.target } ?? targets.first
    }
}

/// The screenshot at a readable size, kept current, with the frame's label and Stop.
private struct EnlargedFrame: View {
    let chat: String
    let name: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.computer
        VStack(alignment: .leading, spacing: 8) {
            ComputerThumbnail(png: store.image(of: chat), width: 640, height: 420)
            HStack(spacing: 8) {
                Text(store.frame(of: chat)?.label ?? name)
                    .font(.ui(TypeSize.ui, .medium))
                    .lineLimit(1)
                    .truncationMode(.middle)
                StatusDot(tone: .running)
                Spacer(minLength: 4)
                Button {
                    shell.stopComputer(chat)
                } label: {
                    Label("Stop", systemImage: Icon.stop)
                }
                .buttonStyle(.nest(.danger))
                .accessibilityLabel("Stop using \(name)")
            }
        }
        .padding(12)
    }
}

/// A screenshot fitted into its box, or a soft box before the first.
struct ComputerThumbnail: View {
    let png: Data?
    let width: Double
    let height: Double

    var body: some View {
        let shape = RoundedRectangle.rounded(7)
        Group {
            if let image = png.flatMap(NSImage.init(data:)) {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
            } else {
                Fireflies(height: 9)
            }
        }
        .frame(width: width, height: height)
        .background(Palette.raised, in: shape)
        .clipShape(shape)
        .overlay(shape.strokeBorder(Palette.divider))
    }
}

extension Shell {
    /// Stop (B150): the chat lets go of what it uses and asks again next time; its turn
    /// stops.
    func stopComputer(_ chat: String) {
        let sessions = sessions
        settingsChange("Could not stop it") { try await sessions.stopComputer(chat) }
    }
}
