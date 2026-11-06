import NestKit
import SwiftUI

/// The map's flat rows, for Find and the remotes (B131): no lanes, a branch by its name, a
/// remote branch naming its remote.
enum FlatRow {
    /// In the small map.
    static let height = 26.0
    /// In the sheet and the picker.
    static let tallHeight = 30.0

    /// A branch name with what Find matched marked; `dim` greys its folders when nothing did.
    static func name(_ name: String, query: String, dim: Bool) -> AttributedString {
        var text = AttributedString(name)
        if !query.isEmpty, let match = text.range(of: query, options: .caseInsensitive) {
            text[match].backgroundColor = Palette.selection
            text[match].foregroundColor = Palette.t1
        } else if dim, let slash = name.lastIndex(of: "/"),
            let folders = text.range(of: String(name[...slash]))
        {
            text[folders].foregroundColor = Palette.t3
        }
        return text
    }
}

/// What a row of Find does, in the map, the sheet or the picker.
struct FoundPicks {
    let selected: (BranchMap.Branch) -> Bool
    let color: (String) -> Color?
    let pick: (BranchMap.Branch) -> Void
    let pickRemote: (BranchMap.RemoteBranch) -> Void
    let add: (String) -> Void
    let addWord: String
    var tall = false
}

private struct FlatNode: View {
    let fill: Color?
    let dotted: Bool

    var body: some View {
        Group {
            if let fill {
                Circle().fill(fill).frame(width: 7, height: 7)
            } else {
                Circle()
                    .stroke(
                        Palette.t3,
                        style: StrokeStyle(lineWidth: 1.4, dash: dotted ? [1.6, 1.9] : [])
                    )
                    .frame(width: 6, height: 6)
            }
        }
        .frame(width: 28, height: 14)
        .accessibilityHidden(true)
    }
}

private struct FlatBranchRow: View {
    let branch: BranchMap.Branch
    let query: String
    let picks: FoundPicks
    @State private var hovering = false

    var body: some View {
        let selected = picks.selected(branch)
        let ink = picks.color(branch.name) ?? Palette.t3
        let adds = hovering && branch.remote == nil
        HStack(spacing: 0) {
            Button {
                picks.pick(branch)
            } label: {
                HStack(spacing: 6) {
                    FlatNode(fill: branch.worktree == nil ? nil : ink, dotted: branch.remote != nil)
                    Text(FlatRow.name(branch.name, query: query, dim: false))
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer(minLength: 0)
                    if let remote = branch.remote {
                        Text(remote).font(.ui(TypeSize.micro)).foregroundStyle(Palette.t3)
                    }
                    if selected, !adds {
                        SelectedCheck(ink: ink)
                    }
                }
                .padding(.trailing, adds ? 6 : 10)
                .flatHit(tall: picks.tall)
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            if adds {
                AddWorktreeChip(branch: branch.name, word: picks.addWord) {
                    picks.add(branch.name)
                }
                .padding(.trailing, 8)
            }
        }
        .flatRow(tall: picks.tall, fill: selected ? ink.opacity(0.14) : nil, hovering: hovering)
        .onHover { hovering = $0 }
        .help(branch.name)
        .accessibilityLabel(branch.name)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// A branch only a remote has; picking it makes the local branch.
struct RemoteRow: View {
    let branch: BranchMap.RemoteBranch
    var query = ""
    var tall = false
    let pick: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: pick) {
            HStack(spacing: 6) {
                FlatNode(fill: nil, dotted: true)
                Text(FlatRow.name(branch.name, query: query, dim: true))
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 0)
                Text(branch.remote).font(.ui(TypeSize.micro)).foregroundStyle(Palette.t3)
            }
            .padding(.trailing, 10)
            .flatHit(tall: tall)
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .flatRow(tall: tall, fill: nil, hovering: hovering)
        .onHover { hovering = $0 }
        .help(branch.id)
        .accessibilityLabel("\(branch.name) on \(branch.remote)")
    }
}

extension View {
    /// The row's full height inside its button, so a click anywhere on the row counts.
    fileprivate func flatHit(tall: Bool) -> some View {
        frame(height: tall ? FlatRow.tallHeight : FlatRow.height)
            .contentShape(Rectangle())
    }

    fileprivate func flatRow(tall: Bool, fill: Color?, hovering: Bool) -> some View {
        font(.ui(tall ? TypeSize.ui : TypeSize.button))
            .foregroundStyle(Palette.sidebarTextOpen)
            .frame(height: tall ? FlatRow.tallHeight : FlatRow.height)
            .background(fill ?? (hovering ? Palette.hover : .clear), in: .rounded(6))
    }
}

/// What Find found, in a list that scrolls past `maxHeight`.
struct FoundRows: View {
    let map: BranchMap
    let query: String
    let picks: FoundPicks
    let maxHeight: Double

    var body: some View {
        let found = map.find(query)
        let height = picks.tall ? FlatRow.tallHeight : FlatRow.height
        if found.isEmpty {
            Text("No branch has that name")
                .font(.ui(TypeSize.button))
                .foregroundStyle(Palette.t3)
                .padding(.horizontal, 9)
                .frame(maxWidth: .infinity, minHeight: FlatRow.height, alignment: .leading)
        } else {
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(found.branches) { branch in
                        FlatBranchRow(branch: branch, query: query, picks: picks)
                    }
                    ForEach(found.remotes) { branch in
                        RemoteRow(branch: branch, query: query, tall: picks.tall) {
                            picks.pickRemote(branch)
                        }
                    }
                }
            }
            .scrollIndicators(.automatic)
            .frame(height: min(Double(found.count) * height, maxHeight))
        }
    }
}

/// The folded "On remotes" row and, opened, what is under it; no remotes, no row.
struct RemoteFold: View {
    /// Find and the full tree reach the rest.
    let remotes: ArraySlice<BranchMap.RemoteBranch>
    let count: Int
    /// A line over it, in the small map.
    let rule: Bool
    var tall = false
    let maxHeight: Double
    let pick: (BranchMap.RemoteBranch) -> Void
    @State private var open = false
    @State private var hovering = false

    var body: some View {
        if count > 0 {
            if rule {
                Divider().overlay(Palette.divider)
            }
            Button {
                open.toggle()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: Icon.chevron)
                        .font(.system(size: 8, weight: .semibold))
                        .rotationEffect(.degrees(open ? 0 : -90))
                    Text("On remotes")
                    Spacer(minLength: 0)
                    Text("\(count)")
                        .font(.ui(TypeSize.micro))
                        .foregroundStyle(Palette.t3)
                        .monospacedDigit()
                }
                .font(.ui(TypeSize.button))
                .foregroundStyle(Palette.t2)
                .padding(EdgeInsets(top: 0, leading: 9, bottom: 0, trailing: 10))
                .frame(height: FlatRow.height)
                .background(hovering ? Palette.hover : .clear, in: .rounded(6))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .pointerStyle(.link)
            .onHover { hovering = $0 }
            .accessibilityValue(open ? "Open" : "Closed")
            if open {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(remotes) { branch in
                            RemoteRow(branch: branch, tall: tall) { pick(branch) }
                        }
                    }
                }
                .scrollIndicators(.automatic)
                .frame(
                    height: min(
                        Double(remotes.count) * (tall ? FlatRow.tallHeight : FlatRow.height),
                        maxHeight))
            }
        }
    }
}
