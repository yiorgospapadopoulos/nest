import HarnessKit
import SwiftUI

/// The right-hand panel of a pixie's page: its details, or Soul, Memory or a note opened
/// from them, each with a way back.
struct PixieDetailsPanel: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        Group {
            switch shell.pixiePanel {
            case .details:
                PixieDetails(pixie: pixie)
            case .soul:
                PixieFilePage(pixie: pixie, name: "soul", title: "Soul", back: "Details") {
                    shell.pixiePanel = .details
                }
            case .memory:
                PixieMemoryPage(pixie: pixie)
            case .note(let note):
                PixieFilePage(pixie: pixie, name: "notes/\(note)", title: note, back: "Memory") {
                    shell.pixiePanel = .memory
                }
            }
        }
        .id("\(pixie.id)/\(shell.pixiePanel)")
    }
}

/// Everything that sets a pixie up, in one scrolling panel laid out like the approved design's
/// Details panel. Every change is saved at once; there is no form to submit (D072).
struct PixieDetails: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell
    @State private var confirming: Confirmation?
    /// "3 facts", once MEMORY.md is read.
    @State private var facts: String?

    private enum Confirmation: Identifiable {
        case reset, delete
        var id: Self { self }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                PixieIdentity(pixie: pixie)
                PixieLook(pixie: pixie)
                    .padding(.top, 14)
                PixieSettings(pixie: pixie)
                    .padding(.top, 16)

                DetailHeading(title: "Projects")
                PixieProjects(pixie: pixie)

                DetailHeading(title: "Skills")
                DetailGroup {
                    ChipList(
                        label: "Skill", add: "Add skill", items: pixie.skills, empty: "All skills"
                    ) { save(UpdatePixieRequest(skills: $0)) }
                    .padding(10)
                }

                DetailHeading(title: "Tools")
                DetailGroup {
                    VStack(alignment: .leading, spacing: 6) {
                        DetailSubheading(title: "Never ask for")
                        ChipList(
                            label: "Never ask for", items: pixie.allowedTools,
                            empty: "Asks as its permission mode says"
                        ) { save(UpdatePixieRequest(allowedTools: $0)) }
                        DetailSubheading(title: "Never allow")
                            .padding(.top, 6)
                        ChipList(
                            label: "Never allow", items: pixie.disallowedTools,
                            empty: "Nothing beyond the git rules"
                        ) { save(UpdatePixieRequest(disallowedTools: $0)) }
                    }
                    .padding(10)
                }

                DetailGroup {
                    DrillInRow(title: "Soul", about: "Who this pixie is and the rules it follows") {
                        shell.pixiePanel = .soul
                    }
                    DetailDivider()
                    DrillInRow(
                        title: "Habits", about: "Recurring tasks this pixie runs on its own",
                        value: "Coming soon")
                    DetailDivider()
                    DrillInRow(
                        title: "Memory", about: "Facts and preferences this pixie remembers",
                        value: facts
                    ) { shell.pixiePanel = .memory }
                }
                .padding(.top, 18)

                DetailGroup {
                    HStack {
                        Text("Hidden").font(.ui(TypeSize.callout))
                        Spacer()
                        Toggle(
                            "Hidden",
                            isOn: Binding(
                                get: { pixie.hidden },
                                set: { save(UpdatePixieRequest(hidden: $0)) })
                        )
                        .toggleStyle(.switch)
                        .controlSize(.mini)
                        .labelsHidden()
                        .pointerStyle(.link)
                    }
                    .padding(.horizontal, 12)
                    .frame(height: 38)
                }
                .padding(.top, 18)
                DetailNote(text: "A hidden pixie leaves the Pixies list. Its chat stays.")

                DetailGroup {
                    DangerRow(
                        title: "Reset conversation", about: "Clear all messages and start fresh"
                    ) {
                        confirming = .reset
                    }
                    DetailDivider()
                    DangerRow(title: "Delete pixie", about: nil) { confirming = .delete }
                }
                .padding(.top, 18)
            }
            .padding(EdgeInsets(top: 18, leading: 14, bottom: 18, trailing: 14))
        }
        .scrollIndicators(.never)
        .task(id: pixie.id) {
            if let memory = try? await shell.pixies.file(pixie.id, name: "memory") {
                facts = PixieMemory.count(memory.text)
            }
        }
        .confirmationDialog(
            confirming == .delete ? "Delete \(pixie.name)?" : "Reset conversation?",
            isPresented: Binding(
                get: { confirming != nil }, set: { if !$0 { confirming = nil } }),
            titleVisibility: .visible, presenting: confirming
        ) { confirmation in
            switch confirmation {
            case .reset:
                Button("Reset", role: .destructive) { shell.resetPixie(pixie.id) }
            case .delete:
                Button("Delete", role: .destructive) { shell.deletePixie(pixie.id) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { confirmation in
            switch confirmation {
            case .reset: Text("The chat is archived. Soul and memory stay.")
            case .delete: Text("Its chat, soul, memory and notes are removed.")
            }
        }
    }

    private func save(_ request: UpdatePixieRequest) {
        shell.updatePixie(pixie.id, request)
    }
}

/// The big sprite, then the name and the @slug, each edited in place.
private struct PixieIdentity: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell
    @State private var editing: Field?
    /// Why the last slug was refused.
    @State private var refused: String?

    private enum Field {
        case name, slug
    }

    var body: some View {
        VStack(spacing: 4) {
            SpriteView(mascot: pixie.mascot, color: pixie.color, size: 96)
                .padding(.bottom, 10)
            if editing == .name {
                InlineField(label: "Name", initial: pixie.name, font: .ui(TypeSize.headline, .bold))
                {
                    editing = nil
                    if let name = $0, !name.isEmpty, name != pixie.name {
                        shell.updatePixie(pixie.id, UpdatePixieRequest(name: name))
                    }
                }
            } else {
                EditableText(text: pixie.name, label: "Edit name") { editing = .name }
                    .font(.ui(TypeSize.headline, .bold))
                    .foregroundStyle(Palette.t1)
            }
            if editing == .slug {
                InlineField(label: "Slug", initial: pixie.slug, font: .ui(TypeSize.callout)) {
                    editing = nil
                    guard let slug = $0, !slug.isEmpty, slug != pixie.slug else { return }
                    Task { refused = await shell.setPixieSlug(pixie.id, slug) }
                }
            } else {
                EditableText(text: "@\(pixie.slug)", label: "Edit slug") {
                    refused = nil
                    editing = .slug
                }
                .font(.ui(TypeSize.callout))
                .foregroundStyle(Palette.t2)
            }
            if let refused {
                Text(refused)
                    .font(.ui(TypeSize.small))
                    .foregroundStyle(StatusTone.failed.textColor)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity)
    }
}

/// Text that turns into a field on click.
private struct EditableText: View {
    let text: String
    let label: String
    let edit: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: edit) {
            Text(text)
                .lineLimit(1)
                .truncationMode(.tail)
                .padding(.horizontal, 8)
                .padding(.vertical, 2)
                .background(
                    hovering ? Palette.fill : .clear,
                    in: RoundedRectangle(cornerRadius: 7, style: .continuous)
                )
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .help(label)
        .accessibilityLabel("\(label), \(text)")
    }
}

/// A field that edits in place: Return or leaving it ends the edit, Escape cancels it.
/// `done` gets the trimmed text, or nil when cancelled.
struct InlineField: View {
    let label: String
    let initial: String
    var font = Font.ui(TypeSize.callout)
    var center = true
    let done: (String?) -> Void
    @State private var text = ""
    @State private var ended = false
    @FocusState private var focused: Bool
    @Environment(\.accentColors) private var accent
    @Environment(\.glass) private var glass

    var body: some View {
        TextField(label, text: $text)
            .textFieldStyle(.plain)
            .font(font)
            .multilineTextAlignment(center ? .center : .leading)
            .padding(.horizontal, 8)
            .frame(height: 28)
            .background(glass.surface, in: glass.rounded(glass.radius.small))
            .overlay(glass.rounded(glass.radius.small).stroke(accent.accent, lineWidth: 1.5))
            .focused($focused)
            .onAppear {
                text = initial
                focused = true
            }
            .onSubmit { end(text) }
            .onExitCommand { end(nil) }
            .onChange(of: focused) { _, now in
                if !now {
                    end(text)
                }
            }
            .accessibilityLabel(label)
    }

    private func end(_ value: String?) {
        guard !ended else { return }
        ended = true
        done(value?.trimmingCharacters(in: .whitespacesAndNewlines))
    }
}

/// Mascots, colours and backgrounds; a click saves the choice.
private struct PixieLook: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            LazyVGrid(
                columns: Array(repeating: GridItem(.flexible(), spacing: 4), count: 5), spacing: 4
            ) {
                ForEach(Mascot.choices, id: \.self) { mascot in
                    MascotChoice(mascot: mascot, color: pixie.color, on: pixie.mascot == mascot) {
                        save(UpdatePixieRequest(mascot: mascot))
                    }
                }
            }
            HStack(spacing: 3) {
                ForEach(PixieColors.presets, id: \.self) { color in
                    ColorDot(color: color, on: pixie.color.uppercased() == color) {
                        save(UpdatePixieRequest(color: color))
                    }
                }
                CustomColorDot(color: pixie.color, on: PixieColor.isCustom(pixie.color)) {
                    save(UpdatePixieRequest(color: $0))
                }
            }
            .frame(maxWidth: .infinity)
            HStack(spacing: 6) {
                ForEach(PixieBackground.choices, id: \.self) { background in
                    BackgroundChoice(background: background, on: pixie.background == background) {
                        save(UpdatePixieRequest(background: background))
                    }
                }
            }
        }
    }

    private func save(_ request: UpdatePixieRequest) {
        shell.updatePixie(pixie.id, request)
    }
}

private struct MascotChoice: View {
    let mascot: Mascot
    let color: String
    let on: Bool
    let pick: () -> Void
    @Environment(\.glass) private var glass

    var body: some View {
        Button(action: pick) {
            HoverReader { hovering in
                SpriteView(mascot: mascot, color: color, size: 30)
                    .frame(maxWidth: .infinity)
                    .frame(height: 40)
                    .background(
                        on ? Palette.fill2 : hovering ? Palette.fill : .clear,
                        in: glass.rounded(glass.radius.item)
                    )
                    .overlay {
                        if on {
                            glass.rounded(glass.radius.item).strokeBorder(Palette.hair2)
                        }
                    }
                    .contentShape(Rectangle())
            }
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(mascot.rawValue.capitalized)
        .accessibilityLabel("Mascot \(mascot.rawValue)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// A preset colour; the chosen one has a ring.
private struct ColorDot: View {
    let color: String
    let on: Bool
    let pick: () -> Void

    var body: some View {
        Button(action: pick) {
            Circle()
                .fill(Color(hex: color))
                .overlay(Circle().strokeBorder(.black.opacity(0.12)))
                .frame(width: 18, height: 18)
                .padding(2.5)
                .overlay {
                    if on {
                        Circle().strokeBorder(Palette.t1, lineWidth: 1.5)
                    }
                }
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .help(color)
        .accessibilityLabel("Colour \(color)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// The rainbow dot: a click opens the system colour picker. The colour is saved once the
/// user stops moving it, not on every step.
private struct CustomColorDot: View {
    let color: String
    let on: Bool
    let pick: (String) -> Void
    @State private var chosen = Color.clear
    @State private var saving: Task<Void, Never>?

    var body: some View {
        ZStack {
            // The picker's own well takes the click, under the rainbow.
            ColorPicker("Custom colour", selection: picked, supportsOpacity: false)
                .labelsHidden()
                .frame(width: 23, height: 23)
                .clipShape(Circle())
            Circle()
                .fill(
                    AngularGradient(
                        colors: [.red, .yellow, .green, .cyan, .blue, .purple, .red],
                        center: .center)
                )
                .overlay(Circle().strokeBorder(.black.opacity(0.12)))
                .frame(width: 18, height: 18)
                .padding(2.5)
                .overlay {
                    if on {
                        Circle().strokeBorder(Palette.t1, lineWidth: 1.5)
                    }
                }
                .allowsHitTesting(false)
        }
        .pointerStyle(.link)
        .help(on ? "Custom colour \(color)" : "Custom colour")
        .accessibilityLabel("Custom colour")
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    private var picked: Binding<Color> {
        Binding(
            get: { Color(hex: color) },
            set: { value in
                guard let rgb = NSColor(value).usingColorSpace(.sRGB) else { return }
                let hex = PixieColor.hex(
                    red: rgb.redComponent, green: rgb.greenComponent, blue: rgb.blueComponent)
                saving?.cancel()
                saving = Task {
                    try? await Task.sleep(for: .milliseconds(600))
                    guard !Task.isCancelled, hex != color else { return }
                    pick(hex)
                }
            })
    }
}

private struct BackgroundChoice: View {
    let background: PixieBackground
    let on: Bool
    let pick: () -> Void
    @Environment(\.glass) private var glass

    var body: some View {
        Button(action: pick) {
            VStack(spacing: 4) {
                glass.rounded(glass.radius.small)
                    .fill(Palette.fill)
                    .overlay(
                        PixieBackdrop(background: background).clipShape(
                            glass.rounded(glass.radius.small))
                    )
                    .overlay(glass.rounded(glass.radius.small).strokeBorder(Palette.hair2))
                    .frame(height: 30)
                    .padding(2)
                    .overlay {
                        if on {
                            glass.rounded(glass.radius.small + 2).strokeBorder(
                                Palette.t1, lineWidth: 1.5)
                        }
                    }
                Text(background.label)
                    .font(.ui(TypeSize.caption, on ? .semibold : .regular))
                    .foregroundStyle(on ? Palette.t1 : Palette.t3)
            }
            .frame(maxWidth: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .accessibilityLabel("\(background.label) background")
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// Model, Thinking, Permissions, Project files and Autonomy: a value on the right that
/// opens a menu of choices.
private struct PixieSettings: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        let agents = shell.agents
        let levels = agents.thinkingLevels(for: pixie.model ?? agents.current.model)
        DetailGroup {
            PickerRow(
                title: "Model",
                value: pixie.model == nil ? "Default" : agents.label(for: pixie.model)
            ) {
                ModelItems(current: pixie.model) { save(UpdatePixieRequest(model: $0.value)) }
            }
            DetailDivider()
            PickerRow(
                title: "Thinking",
                value: levels.isEmpty ? "Not available" : pixie.effort?.label ?? "Default",
                enabled: !levels.isEmpty
            ) {
                ThinkingItems(model: pixie.model ?? agents.current.model, effort: pixie.effort) {
                    if let effort = $0 {
                        save(UpdatePixieRequest(effort: effort))
                    }
                }
            }
            DetailDivider()
            PickerRow(title: "Permissions", value: pixie.permissionMode.label) {
                Section("Permission mode") {
                    ForEach(PermissionMode.selectable, id: \.self) { mode in
                        OptionItem(
                            title: mode.label, detail: mode.summary,
                            checked: pixie.permissionMode == mode
                        ) { save(UpdatePixieRequest(permissionMode: mode)) }
                    }
                }
            }
            DetailDivider()
            PickerRow(title: "Project files", value: pixie.projectAccess.label) {
                Section("Project files") {
                    ForEach(ProjectAccess.choices, id: \.self) { access in
                        OptionItem(
                            title: access.label, detail: access.summary,
                            checked: pixie.projectAccess == access
                        ) { save(UpdatePixieRequest(projectAccess: access)) }
                    }
                }
            }
            DetailDivider()
            PickerRow(title: "Autonomy", value: pixie.autonomy.label) {
                Section("Autonomy") {
                    ForEach(Autonomy.choices, id: \.self) { autonomy in
                        OptionItem(
                            title: autonomy.label, detail: autonomy.summary,
                            checked: pixie.autonomy == autonomy
                        ) { save(UpdatePixieRequest(autonomy: autonomy)) }
                    }
                }
            }
        }
    }

    private func save(_ request: UpdatePixieRequest) {
        shell.updatePixie(pixie.id, request)
    }
}

/// A title on the left and the value on the right; a click opens the choices.
private struct PickerRow<Items: View>: View {
    let title: String
    let value: String
    var enabled = true
    @ViewBuilder let items: () -> Items
    @State private var hovering = false

    var body: some View {
        Menu {
            items()
        } label: {
            HStack(spacing: 8) {
                Text(title)
                    .font(.ui(TypeSize.callout))
                    .foregroundStyle(Palette.t1)
                Spacer(minLength: 8)
                Text(value)
                    .font(.ui(TypeSize.callout))
                    .foregroundStyle(Palette.t2)
                    .lineLimit(1)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(Palette.t3)
            }
            .padding(.horizontal, 12)
            .frame(height: 36)
            .background(hovering && enabled ? Palette.fill : .clear)
            .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .disabled(!enabled)
        .pointerStyle(enabled ? .link : nil)
        .onHover { hovering = $0 }
        .accessibilityLabel("\(title): \(value)")
    }
}

/// Every project, or the ones picked from the registered repos.
private struct PixieProjects: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        let chosen = pixie.projects
        DetailGroup {
            if let chosen {
                if chosen.isEmpty {
                    DetailLine(text: "No projects", dim: true)
                    DetailDivider()
                }
                ForEach(chosen, id: \.self) { name in
                    HStack(spacing: 9) {
                        ProjectMarkView(name: name)
                        Text(name).font(.ui(TypeSize.callout)).lineLimit(1)
                        Spacer(minLength: 4)
                        RemoveButton(label: "Remove \(name)") {
                            save(UpdatePixieRequest(projects: chosen.filter { $0 != name }))
                        }
                    }
                    .padding(.horizontal, 12)
                    .frame(height: 36)
                    DetailDivider()
                }
            } else {
                DetailLine(text: "All projects", dim: false)
                DetailDivider()
            }
            AddMenuRow(title: "Add project") {
                if chosen != nil {
                    Button("All projects") { save(UpdatePixieRequest(allProjects: true)) }
                    Divider()
                }
                ForEach(shell.app.repos.filter { !(chosen ?? []).contains($0.name) }) { repo in
                    Button(repo.name) {
                        save(UpdatePixieRequest(projects: (chosen ?? []) + [repo.name]))
                    }
                }
            }
        }
    }

    private func save(_ request: UpdatePixieRequest) {
        shell.updatePixie(pixie.id, request)
    }
}

/// "+ Add …" opening a menu.
private struct AddMenuRow<Items: View>: View {
    let title: String
    @ViewBuilder let items: () -> Items
    @State private var hovering = false

    var body: some View {
        Menu {
            items()
        } label: {
            HStack(spacing: 7) {
                Image(systemName: Icon.plus).font(.system(size: 11, weight: .semibold))
                Text(title).font(.ui(TypeSize.callout))
                Spacer(minLength: 0)
            }
            .foregroundStyle(hovering ? Palette.t1 : Palette.t2)
            .padding(.horizontal, 12)
            .frame(height: 36)
            .background(hovering ? Palette.fill : .clear)
            .contentShape(Rectangle())
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .accessibilityLabel(title)
    }
}

/// Removable chips and a field to add one more, saved as soon as it changes.
private struct ChipList: View {
    /// The field's name, also in "Add to <label>" unless `add` names the button.
    let label: String
    var add: String?
    let items: [String]
    let empty: String
    let change: ([String]) -> Void
    @State private var adding = false
    @Environment(\.glass) private var glass

    var body: some View {
        FlowLayout(spacing: 6) {
            if items.isEmpty && !adding {
                Text(empty)
                    .font(.ui(TypeSize.small))
                    .foregroundStyle(Palette.t3)
                    .frame(height: 24)
            }
            ForEach(items, id: \.self) { item in
                HStack(spacing: 3) {
                    Text(item)
                        .font(.mono(11))
                        .foregroundStyle(Palette.t1)
                        .lineLimit(1)
                    RemoveButton(label: "Remove \(item)") {
                        change(items.filter { $0 != item })
                    }
                }
                .padding(.leading, 8)
                .padding(.trailing, 2)
                .frame(height: 24)
                .background(Palette.fill2, in: glass.rounded(glass.radius.small))
            }
            if adding {
                InlineField(label: label, initial: "", font: .mono(11), center: false) { text in
                    adding = false
                    if let text, !text.isEmpty, !items.contains(text) {
                        change(items + [text])
                    }
                }
                .frame(width: 180)
            } else {
                Button {
                    adding = true
                } label: {
                    Label("Add", systemImage: Icon.plus)
                }
                .buttonStyle(.harness(.ghost, height: 24))
                .accessibilityLabel(add ?? "Add to \(label)")
            }
        }
    }
}

/// Lays its views out in rows, wrapping to the next row when one is full.
private struct FlowLayout: Layout {
    var spacing = 6.0

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = rows(width: proposal.width ?? .infinity, subviews: subviews)
        let height = rows.map(\.height).reduce(0, +) + spacing * Double(max(rows.count - 1, 0))
        let width = rows.map(\.width).max() ?? 0
        return CGSize(width: proposal.width ?? width, height: height)
    }

    func placeSubviews(
        in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()
    ) {
        var y = bounds.minY
        for row in rows(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for index in row.indices {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(
                    at: CGPoint(x: x, y: y + (row.height - size.height) / 2),
                    proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row {
        var indices: [Int] = []
        var width = 0.0
        var height = 0.0
    }

    private func rows(width: Double, subviews: Subviews) -> [Row] {
        var rows: [Row] = []
        var row = Row()
        for index in subviews.indices {
            var size = subviews[index].sizeThatFits(.unspecified)
            size.width = min(size.width, width)
            if !row.indices.isEmpty && row.width + spacing + size.width > width {
                rows.append(row)
                row = Row()
            }
            row.width += (row.indices.isEmpty ? 0 : spacing) + size.width
            row.height = max(row.height, size.height)
            row.indices.append(index)
        }
        if !row.indices.isEmpty {
            rows.append(row)
        }
        return rows
    }
}

/// A row that opens a page: title, a line about it, a count or note, and a chevron. With
/// no action it is shown dimmed, as Habits is for now.
private struct DrillInRow: View {
    let title: String
    let about: String
    var value: String?
    var open: (() -> Void)?
    @State private var hovering = false

    var body: some View {
        Button {
            open?()
        } label: {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.ui(TypeSize.callout, .semibold))
                        .foregroundStyle(Palette.t1)
                    Text(about)
                        .font(.ui(TypeSize.small))
                        .foregroundStyle(Palette.t3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if let value {
                    Text(value)
                        .font(.ui(TypeSize.small))
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .fixedSize()
                }
                if open != nil {
                    Image(systemName: Icon.chevronRight)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Palette.t3)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .background(hovering && open != nil ? Palette.fill : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(open == nil)
        .opacity(open == nil ? 0.6 : 1)
        .pointerStyle(open == nil ? nil : .link)
        .onHover { hovering = $0 }
        .accessibilityLabel(value.map { "\(title), \($0)" } ?? title)
    }
}

/// A red action at the bottom, such as Reset conversation.
private struct DangerRow: View {
    let title: String
    let about: String?
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.ui(TypeSize.callout, .semibold))
                    .foregroundStyle(StatusTone.failed.textColor)
                if let about {
                    Text(about)
                        .font(.ui(TypeSize.small))
                        .foregroundStyle(Palette.t3)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .background(hovering ? StatusTone.failed.soft : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .accessibilityLabel(title)
        .accessibilityHint(about ?? "")
    }
}

/// A small x that removes the thing beside it.
struct RemoveButton: View {
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: Icon.close).font(.system(size: 8, weight: .bold))
        }
        .buttonStyle(SmallSquareStyle())
        .help(label)
        .accessibilityLabel(label)
    }
}

/// The rows of one part of the details, on an inset fill.
struct DetailGroup<Content: View>: View {
    @ViewBuilder let content: () -> Content
    @Environment(\.glass) private var glass

    var body: some View {
        VStack(alignment: .leading, spacing: 0, content: content)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.fill, in: glass.rounded(glass.radius.card))
            .clipShape(glass.rounded(glass.radius.card))
    }
}

struct DetailHeading: View {
    let title: String

    var body: some View {
        Text(title.uppercased())
            .font(.ui(TypeSize.caption, .bold))
            .tracking(0.66)
            .foregroundStyle(Palette.t3)
            .padding(.leading, 4)
            .padding(.top, 18)
            .padding(.bottom, 6)
    }
}

struct DetailSubheading: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.ui(TypeSize.small, .semibold))
            .foregroundStyle(Palette.t2)
    }
}

struct DetailDivider: View {
    var body: some View {
        Rectangle().fill(Palette.hair).frame(height: 1).padding(.leading, 12)
    }
}

/// A plain row of text in a group.
struct DetailLine: View {
    let text: String
    let dim: Bool

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.callout))
            .foregroundStyle(dim ? Palette.t3 : Palette.t1)
            .padding(.horizontal, 12)
            .frame(height: 36)
    }
}

/// A short note under a group.
struct DetailNote: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.small))
            .foregroundStyle(Palette.t3)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 4)
            .padding(.top, 6)
    }
}
