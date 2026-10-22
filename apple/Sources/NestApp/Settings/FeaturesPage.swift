import NestKit
import SwiftUI

/// Settings > Features (B103): what makes Nest different, one fold-open row per area. The
/// features the page shows are reported at once; their "New", the groups' dots and the
/// sidebar's count stay until the Settings window closes.
struct FeaturesPage: View {
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.features
        VStack(alignment: .leading, spacing: 0) {
            Text(store.intro)
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 14)
            if let catalog = store.catalog {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(catalog.groups) { group in
                        FeatureGroupView(group: group)
                    }
                }
                .overlay(alignment: .top) { Separator() }
                .padding(.top, 18)
                if let footer = store.footer {
                    Text(footer)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .padding(.top, 14)
                }
            } else {
                Fireflies().padding(.vertical, 24)
            }
        }
        .task {
            try? await store.load()
            await store.pageShown()
        }
    }
}

/// A group's row, with its features under it while open.
private struct FeatureGroupView: View {
    let group: FeatureGroup
    @Environment(Shell.self) private var shell

    var body: some View {
        let store = shell.model.features
        let open = store.isOpen(group)
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.smooth(duration: 0.2)) { store.toggle(group) }
                if store.isOpen(group) {
                    Task { try? await store.markShown(store.shownIDs) }
                }
            } label: {
                HStack(spacing: 10) {
                    Text(group.name).font(.ui(TypeSize.ui, .medium))
                    Spacer(minLength: 8)
                    if store.hasNew(group) {
                        Circle()
                            .fill(StatusTone.running.color)
                            .frame(width: 6, height: 6)
                            .accessibilityLabel("Has new")
                    }
                    Text("\(group.features.count)")
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                        .monospacedDigit()
                    Image(systemName: Icon.chevronRight)
                        .font(.system(size: 8, weight: .semibold))
                        .foregroundStyle(Palette.t3)
                        .rotationEffect(.degrees(open ? 90 : 0))
                        .frame(width: 10)
                }
                .padding(.vertical, 11)
                .frame(minHeight: 40)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .accessibilityLabel("\(group.name), \(group.features.count) features")
            .accessibilityValue(open ? "Expanded" : "Collapsed")
            if open {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(group.features) { feature in
                        FeatureRow(feature: feature, isNew: store.isNew(feature))
                    }
                }
                .padding(.leading, 16)
                .padding(.bottom, 6)
            }
        }
        .overlay(alignment: .bottom) { Separator() }
    }
}

/// A feature: an optional New badge, its name and text, and where to find it on the right.
private struct FeatureRow: View {
    let feature: Feature
    /// New on this device, or it was when the page showed during this visit to Settings.
    let isNew: Bool

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                if isNew {
                    NewBadge()
                }
                Text(styled)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Text(feature.place)
                .font(.ui(TypeSize.meta))
                .foregroundStyle(Palette.t3)
                .lineLimit(1)
                .fixedSize()
        }
        .padding(.vertical, 9)
        .overlay(alignment: .top) { Separator() }
        .accessibilityElement(children: .combine)
    }

    /// The name, then the text in the secondary colour with its code in mono.
    private var styled: AttributedString {
        var name = AttributedString(feature.name + "  ")
        name.font = .ui(TypeSize.ui, .medium)
        name.foregroundColor = Palette.t1
        return feature.parts.reduce(into: name) { result, part in
            var run = AttributedString(part.text)
            run.foregroundColor = Palette.t2
            if part.isCode {
                run.font = .mono(TypeSize.meta)
                run.backgroundColor = Palette.soft
            } else {
                run.font = .ui(TypeSize.ui)
            }
            result += run
        }
    }
}

/// "New" in the run colour on its soft fill.
private struct NewBadge: View {
    var body: some View {
        Text("New")
            .font(.ui(10.5, .semibold))
            .foregroundStyle(StatusTone.running.color)
            .padding(.horizontal, 6)
            .padding(.vertical, 1)
            .background(StatusTone.running.color.opacity(0.12), in: .rounded(4))
    }
}
