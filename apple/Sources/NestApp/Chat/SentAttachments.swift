import AppKit
import NestKit
import SwiftUI

/// A message's images, then its other files, read with the device token while on screen.
/// The images keep a fixed box, as no size is stored, so the transcript does not jump.
struct SentAttachments: View {
    let attachments: [Attachment]
    var alignment = HorizontalAlignment.trailing

    var body: some View {
        let images = attachments.filter(\.isImage)
        let files = attachments.filter { !$0.isImage }
        VStack(alignment: alignment, spacing: 6) {
            if !images.isEmpty {
                FlowLayout(spacing: 8, trailing: alignment == .trailing) {
                    ForEach(images) { SentImage(attachment: $0) }
                }
            }
            ForEach(files) { SentFileRow(attachment: $0) }
        }
    }
}

private struct SentImage: View {
    static let box = CGSize(width: 240, height: 150)

    let attachment: Attachment
    @Environment(Shell.self) private var shell
    /// Its thumbnail is ready; it lives in `SentThumbnails`, for the next time it scrolls by.
    @State private var prepared = false

    var body: some View {
        let id = attachment.id
        Group {
            if shell.images.deleted(id) {
                note("Image deleted")
            } else if shell.images.failed(id) || (prepared && SentThumbnails.image(id) == nil) {
                note("Image not available")
            } else if let picture = SentThumbnails.image(id) {
                Button {
                    shell.show(.image(id))
                } label: {
                    Image(nsImage: picture)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: Self.box.width, height: Self.box.height)
                        .softFill()
                        .clipShape(.rounded(Radius.card))
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .help("Open full size")
                .accessibilityLabel("Open \(attachment.filename)")
            } else {
                Color.clear
                    .frame(width: Self.box.width, height: Self.box.height)
                    .softFill()
            }
        }
        .task(id: id) {
            await shell.images.load(id)
            if let data = shell.images.data(for: id) {
                await SentThumbnails.prepare(id, from: data)
                prepared = true
            }
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .frame(width: Self.box.width, height: 64)
            .overlay {
                RoundedRectangle.rounded(Radius.card)
                    .strokeBorder(Palette.divider, style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
            }
    }
}

/// Small copies of sent images: the full ones can be 2000 pixels across, too much to decode
/// while the transcript scrolls.
@MainActor private enum SentThumbnails {
    /// The box at twice its size, for Retina.
    private nonisolated static let edge = 480
    private static let cache: NSCache<NSString, NSImage> = {
        let cache = NSCache<NSString, NSImage>()
        cache.countLimit = 200
        return cache
    }()

    static func image(_ id: String) -> NSImage? {
        cache.object(forKey: id as NSString)
    }

    static func prepare(_ id: String, from data: Data) async {
        guard image(id) == nil else { return }
        let png = await Task.detached(priority: .userInitiated) {
            ImageAttachment.thumbnail(data, edge: edge)
        }.value
        if let png, let image = NSImage(data: png) {
            cache.setObject(image, forKey: id as NSString)
        }
    }
}

/// A file with its type, name and size; a click saves it where the user picks, never runs it.
private struct SentFileRow: View {
    let attachment: Attachment
    @Environment(Shell.self) private var shell

    var body: some View {
        let deleted = shell.images.deleted(attachment.id)
        Group {
            if deleted {
                row(note: "Deleted").opacity(0.55)
            } else {
                Button {
                    shell.saveAttachment(attachment)
                } label: {
                    row(note: StorageText.bytes(attachment.size))
                }
                .buttonStyle(.plain)
                .pointerStyle(.link)
                .help("Save \(attachment.filename)")
                .accessibilityLabel("Save \(attachment.filename)")
            }
        }
        .task(id: attachment.id) { await shell.images.check(attachment.id) }
    }

    private func row(note: String) -> some View {
        HStack(spacing: 12) {
            Text(attachment.typeTag)
                .font(.ui(9, .semibold))
                .foregroundStyle(Palette.t3)
                .frame(width: 28, height: 32)
                .background(Palette.divider, in: .rounded(Radius.chip))
            Text(attachment.filename)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t1)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(note)
                .font(.ui(TypeSize.meta))
                .monospacedDigit()
                .foregroundStyle(Palette.t3)
                .fixedSize()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(width: 280)
        .softFill()
        .overlay {
            RoundedRectangle.rounded(Radius.card).strokeBorder(Palette.divider, lineWidth: 1)
        }
    }
}
