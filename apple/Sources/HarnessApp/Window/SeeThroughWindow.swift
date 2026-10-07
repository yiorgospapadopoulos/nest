import AppKit
import CoreImage
import HarnessKit
import SwiftUI

/// Makes the window see-through: non-opaque with a clear background and its content
/// under a transparent title bar, with the system's behind-window blur beneath
/// everything. The blur turns opaque by itself with Reduce Transparency.
struct SeeThroughWindow: NSViewRepresentable {
    /// The theme's material, lighter to denser (see `WindowGlass`).
    let material: WindowGlass.Material
    @Environment(\.flatGlass) private var flat

    func makeNSView(context: Context) -> NSView {
        // Offscreen snapshots have no desktop to blur and keep their window as it is.
        guard !flat else { return NSView() }
        let view = SeeThroughEffectView()
        view.blendingMode = .behindWindow
        view.state = .active
        updateNSView(view, context: context)
        return view
    }

    func updateNSView(_ view: NSView, context: Context) {
        guard let effect = view as? NSVisualEffectView else { return }
        // Clear has no window blur: the view stays (it keeps the window see-through) but
        // draws nothing.
        effect.alphaValue = material == .none ? 0 : 1
        effect.material = Self.material(material)
    }

    /// The system materials for the theme's blur. macOS fixes the blur radius; the
    /// materials differ in how much they frost and tint what is behind.
    static func material(_ material: WindowGlass.Material) -> NSVisualEffectView.Material {
        switch material {
        case .none, .medium: .sidebar
        case .heavy: .popover
        }
    }
}

private final class SeeThroughEffectView: NSVisualEffectView {
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard let window else { return }
        window.isOpaque = false
        window.backgroundColor = .clear
        window.titlebarAppearsTransparent = true
        window.styleMask.insert(.fullSizeContentView)
    }
}

#if DEBUG
    /// A busy stand-in for the desktop behind a see-through window in snapshots: bright
    /// shapes and other windows' text, blurred about as much as the system blurs them.
    /// Offscreen captures leave out SwiftUI's blur, so the blur is baked into an image.
    struct SampleDesktop: View {
        @Environment(\.colorScheme) private var scheme

        var body: some View {
            let dark = scheme == .dark
            Group {
                if let image = Self.blurred(dark: dark) {
                    Image(nsImage: image).resizable()
                } else {
                    Self.scene(dark: dark)
                }
            }
            .overlay(dark ? Color.black.opacity(0.25) : Color.white.opacity(0.2))
            .ignoresSafeArea()
            .allowsHitTesting(false)
        }

        private static var cache: [Bool: NSImage] = [:]

        private static func blurred(dark: Bool) -> NSImage? {
            if let image = cache[dark] {
                return image
            }
            let renderer = ImageRenderer(content: scene(dark: dark))
            guard let cgImage = renderer.cgImage else { return nil }
            let input = CIImage(cgImage: cgImage)
            let blur = CIFilter(name: "CIGaussianBlur")!
            blur.setValue(input.clampedToExtent(), forKey: kCIInputImageKey)
            blur.setValue(30, forKey: kCIInputRadiusKey)
            guard let output = blur.outputImage?.cropped(to: input.extent),
                let result = CIContext().createCGImage(output, from: input.extent)
            else { return nil }
            let image = NSImage(cgImage: result, size: CGSize(width: 1440, height: 900))
            cache[dark] = image
            return image
        }

        private static func scene(dark: Bool) -> some View {
            ZStack(alignment: .topLeading) {
                LinearGradient(
                    colors: dark
                        ? [
                            Color(red: 0.05, green: 0.10, blue: 0.25),
                            Color(red: 0.30, green: 0.08, blue: 0.22),
                        ]
                        : [
                            Color(red: 0.98, green: 0.62, blue: 0.30),
                            Color(red: 0.25, green: 0.55, blue: 0.95),
                        ],
                    startPoint: .topLeading, endPoint: .bottomTrailing)
                Circle().fill(Color(red: 0.95, green: 0.20, blue: 0.35))
                    .frame(width: 520).offset(x: 760, y: 380)
                Circle().fill(Color(red: 0.15, green: 0.85, blue: 0.55))
                    .frame(width: 380).offset(x: 120, y: 520)
                Capsule().fill(Color(red: 1, green: 0.85, blue: 0.10))
                    .frame(width: 700, height: 160).rotationEffect(.degrees(-18))
                    .offset(x: 380, y: 120)
                otherWindow(dark: dark).offset(x: 60, y: 80)
                otherWindow(dark: !dark).offset(x: 900, y: 140)
            }
            .frame(width: 1440, height: 900, alignment: .topLeading)
            .environment(\.colorScheme, dark ? .dark : .light)
        }

        private static func otherWindow(dark: Bool) -> some View {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(0..<12, id: \.self) { line in
                    Text("Another window's text, line \(line + 1), in a busy desktop behind")
                        .font(.system(size: 15, weight: line == 0 ? .bold : .regular))
                }
            }
            .foregroundStyle(dark ? .white : .black)
            .padding(24)
            .frame(width: 480, alignment: .leading)
            .background(dark ? Color(white: 0.12) : Color.white)
            .clipShape(RoundedRectangle(cornerRadius: 14))
        }
    }
#endif
