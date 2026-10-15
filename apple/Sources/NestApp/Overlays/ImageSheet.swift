import AppKit
import NestKit
import SwiftUI

/// A tool result's image at full size, scaled down to fit the window (B59).
struct ImageSheet: View {
    let attachment: String
    @Environment(Shell.self) private var shell

    var body: some View {
        SheetFrame(title: "Image", width: 900, maxHeight: 900) {
            if let data = shell.images.data(for: attachment), let picture = NSImage(data: data) {
                Image(nsImage: picture)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxWidth: picture.size.width, maxHeight: picture.size.height)
                    .padding(.vertical, 14)
                    .accessibilityLabel("Image from the tool")
            } else {
                Text("Image not available")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
                    .padding(.vertical, 14)
            }
        }
    }
}
