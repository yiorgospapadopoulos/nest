import AppKit
import NestKit
import SwiftUI

/// A tool result's or a sent message's image at full size, scaled down to fit the window
/// (B59). It reads the image itself: the chats are web panes, which keep their own copies
/// (B144).
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
                    .accessibilityLabel("Image")
            } else if shell.images.deleted(attachment) || shell.images.failed(attachment) {
                Text(shell.images.deleted(attachment) ? "Image deleted" : "Image not available")
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(Palette.t3)
                    .padding(.vertical, 14)
            } else {
                ProgressView()
                    .controlSize(.small)
                    .padding(.vertical, 14)
            }
        }
        .task(id: attachment) {
            await shell.images.load(attachment)
        }
    }
}
