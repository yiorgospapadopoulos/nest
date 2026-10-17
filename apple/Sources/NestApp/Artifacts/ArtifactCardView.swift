import NestKit
import SwiftUI

/// A chat saved an artifact: its kind, title and "Saved" or "Version 3", and Open, which
/// shows that version in the Artifacts view. Once the artifact is deleted the card says
/// so and Open is off.
struct ArtifactCardView: View {
    let card: ArtifactCard
    let chat: String
    @Environment(Shell.self) private var shell

    var body: some View {
        let deleted = shell.artifacts.availability(of: card.artifactID) == .deleted
        HStack(spacing: 10) {
            Image(systemName: card.kind.icon)
                .font(.system(size: 13))
                .foregroundStyle(Palette.t2)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 3) {
                Text(card.title)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(deleted ? Palette.t3 : Palette.t1)
                    .lineLimit(1)
                Text(
                    "\(ArtifactText.kind(card.kind)) · \(deleted ? ArtifactText.deleted : ArtifactText.cardState(card))"
                )
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Button("Open") {
                shell.openArtifact(card.artifactID, version: card.version, from: chat)
            }
            .buttonStyle(.nest(.soft))
            .fixedSize()
            .disabled(deleted)
            .help(deleted ? "This artifact was deleted" : "Open \(card.title) in Artifacts")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .softFill()
        .accessibilityElement(children: .contain)
        .task(id: card.artifactID) { await shell.artifacts.check(card.artifactID) }
    }
}
