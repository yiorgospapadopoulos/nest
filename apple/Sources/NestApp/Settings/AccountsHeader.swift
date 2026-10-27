import SwiftUI

/// An Accounts section's title line, as the More engines design has it (B107): a mark and
/// the name in the brightest text, so each engine, More engines, the local models and
/// GitHub stand apart.
struct AccountsHeader<Mark: View>: View {
    let title: String
    @ViewBuilder let mark: () -> Mark

    var body: some View {
        HStack(spacing: 7) {
            mark()
            Text(title)
                .font(.ui(13, .semibold))
                .foregroundStyle(Palette.t1)
        }
        .foregroundStyle(Palette.t1)
        .padding(.bottom, 8)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}

extension AccountsHeader where Mark == EngineMark {
    /// An engine's section: its own mark.
    init(engine: String, title: String) {
        self.init(title: title) { EngineMark(provider: engine, size: 14) }
    }
}

/// A symbol in an engine mark's place, for More engines, the local models and GitHub.
struct AccountsSymbol: View {
    let name: String

    var body: some View {
        Image(systemName: name)
            .font(.system(size: 12, weight: .medium))
            .frame(width: 14, height: 14)
            .accessibilityHidden(true)
    }
}
