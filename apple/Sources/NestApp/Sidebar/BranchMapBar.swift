import NestKit
import SwiftUI

/// The map's Find field, and the picker's.
struct FindField: View {
    let placeholder: String
    @Binding var text: String
    var size = TypeSize.button

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: Icon.search).font(.system(size: 10))
            TextField(placeholder, text: $text)
                .textFieldStyle(.plain)
                .font(.ui(size))
                .foregroundStyle(Palette.t1)
                .autocorrectionDisabled()
                .accessibilityLabel(placeholder)
        }
        .foregroundStyle(Palette.t3)
    }
}

/// The header of the small map and of the full tree: Find, Reload and what follows them,
/// then any remote that failed (B131). Nothing here waits for the fetch.
struct MapBar<Trailing: View>: View {
    let project: String
    @Binding var query: String
    var height = 28.0
    var leading = 8.0
    @ViewBuilder let trailing: () -> Trailing
    @Environment(Shell.self) private var shell
    @Environment(\.reducedMotion) private var reduceMotion

    var body: some View {
        let reload = shell.branchMaps.reload(of: project)
        HStack(spacing: 2) {
            FindField(placeholder: "Find a branch", text: $query)
            Spacer(minLength: 0)
            MapBarButton(
                icon: Icon.refresh, label: "Reload", active: reload.running,
                spins: reload.running && !reduceMotion
            ) {
                shell.reloadRemotes(of: project)
            }
            trailing()
        }
        .padding(EdgeInsets(top: 0, leading: leading, bottom: 0, trailing: 4))
        .frame(height: height)
        .overlay(alignment: .bottom) {
            Divider().overlay(Palette.divider)
            if reload.running, !reduceMotion {
                ColoredLayerMark<ReloadProgressLayer>(color: Palette.t2).frame(height: 1)
            }
        }
        ForEach(reload.failures) { failure in
            HStack(alignment: .top, spacing: 6) {
                let remotes = Text(failure.remotes)
                    .font(.mono(10.5, .medium))
                    .foregroundStyle(StatusTone.failed.color)
                Text("\(remotes) \(failure.reason)")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true)
                MapBarButton(icon: Icon.close, label: "Dismiss", side: 16) {
                    shell.branchMaps.dismissFailures(of: project)
                }
            }
            .padding(EdgeInsets(top: 5, leading: leading, bottom: 5, trailing: 4))
            .overlay(alignment: .bottom) { Divider().overlay(Palette.divider) }
        }
    }
}

/// A small square icon button of the map's header.
struct MapBarButton: View {
    let icon: String
    let label: String
    var side = 22.0
    var active = false
    var spins = false
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: side * 0.5, weight: .regular))
                .symbolEffect(.rotate, options: .repeat(.continuous), isActive: spins)
                .foregroundStyle(active || hovering ? Palette.t1 : Palette.t3)
                .frame(width: side, height: side)
                .background(hovering ? Palette.soft : .clear, in: .rounded(5))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .help(label)
        .accessibilityLabel(label)
    }
}

/// A short bar crossing the view for as long as a reload runs.
private final class ReloadProgressLayer: ColoredMotionView {
    private var width = 0.0

    override func layout() {
        super.layout()
        if bounds.width != width {
            width = bounds.width
            restartMotion()
        }
    }

    override func startMotion(in layer: CALayer) {
        guard let color, width > 0 else { return }
        layer.masksToBounds = true
        let bar = CALayer()
        bar.backgroundColor = color.cgColor
        bar.frame = CGRect(x: 0, y: 0, width: width * 0.4, height: 1)
        layer.sublayers = [bar]
        let slide = CABasicAnimation(keyPath: "position.x")
        slide.fromValue = -width * 0.2
        slide.toValue = width * 1.2
        slide.timingFunction = LayerLoop.easeInOut
        LayerLoop.run(slide, period: 1.4, on: bar)
    }
}
