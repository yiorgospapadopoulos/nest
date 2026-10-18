import NestKit
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
            case .activity:
                PixieActivityPage(pixie: pixie)
            case .note(let note):
                PixieFilePage(pixie: pixie, name: "notes/\(note)", title: note, back: "Memory") {
                    shell.pixiePanel = .memory
                }
            case .habits:
                PixieHabitsPage(pixie: pixie)
            case .habit(let id):
                HabitEditor(pixie: pixie, habitID: id)
            case .habitHistory(let id):
                HabitHistoryPage(pixie: pixie, habitID: id)
            }
        }
        .id("\(pixie.id)/\(shell.pixiePanel)")
    }
}

/// Everything that sets a pixie up, in one scrolling panel laid out like Monocode's
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
                    .padding(.top, 12)
                    .padding(.horizontal, 8)
                SectionBreak()
                PixieSettings(pixie: pixie)

                DetailHeading(title: "Limits")
                PixieLimitRows(pixie: pixie)

                PixieSkillChips(pixie: pixie)

                SectionBreak()
                DetailGroup {
                    DrillInRow(title: "Soul", about: "Who this pixie is and the rules it follows") {
                        shell.pixiePanel = .soul
                    }
                    DrillInRow(
                        title: "Habits", about: "Recurring tasks this pixie runs on its own",
                        value: habitCount
                    ) { shell.pixiePanel = .habits }
                    DrillInRow(
                        title: "Memory", about: "Facts and preferences this pixie remembers",
                        value: facts
                    ) { shell.pixiePanel = .memory }
                    DrillInRow(
                        title: "Activity", about: "What it did in your chats with its tools"
                    ) { shell.pixiePanel = .activity }
                }

                DetailHeading(title: "Artifacts")
                PixieArtifacts(pixie: pixie)

                SectionBreak()
                DetailGroup {
                    HStack {
                        Text("Hidden").font(.ui(TypeSize.ui)).foregroundStyle(Palette.t1)
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
                    .padding(.horizontal, 8)
                    .frame(height: Metrics.rowHeight + 2)
                }
                DetailNote(text: "A hidden pixie leaves the Pixies list. Its chat stays.")

                SectionBreak()
                DetailGroup {
                    DangerRow(
                        title: "Reset conversation", about: "Clear all messages and start fresh"
                    ) {
                        confirming = .reset
                    }
                    DangerRow(title: "Delete pixie", about: nil) { confirming = .delete }
                }
            }
            .padding(EdgeInsets(top: 18, leading: 6, bottom: 14, trailing: 6))
        }
        .scrollIndicators(.never)
        // Read quietly, again when the pixie changes or its chat ends a turn (it may have
        // remembered something); coming back from Memory opens these details afresh.
        .task(id: FactsKey(pixie: pixie, working: working)) {
            if let memory = try? await shell.pixies.file(pixie.id, name: "memory") {
                facts = PixieMemory.count(memory.text)
            }
            if shell.habits.habits(of: pixie.id) == nil {
                try? await shell.habits.load(pixie.id)
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

    /// "2 habits", once read.
    private var habitCount: String? {
        shell.habits.habits(of: pixie.id).map {
            $0.count == 1 ? "1 habit" : "\($0.count) habits"
        }
    }

    /// The pixie's chat runs a turn.
    private var working: Bool {
        pixie.chatSessionID.flatMap(shell.sessions.session)?.state.isInFlight ?? false
    }

    private struct FactsKey: Hashable {
        let id: String
        let updatedAt: Date
        let working: Bool

        init(pixie: Pixie, working: Bool) {
            id = pixie.id
            updatedAt = pixie.updatedAt
            self.working = working
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
        VStack(spacing: 2) {
            let working = shell.isWorking(pixie)
            SpriteView(
                mascot: pixie.mascot, color: pixie.color, size: 63, working: working,
                phaseKey: pixie.id
            )
            .overlay(alignment: .topTrailing) {
                StillWorkingDot(working: working).offset(x: 8, y: -4)
            }
            .padding(.bottom, 10)
            if editing == .name {
                InlineField(label: "Name", initial: pixie.name, font: .ui(TypeSize.body, .semibold))
                {
                    editing = nil
                    if let name = $0, !name.isEmpty, name != pixie.name {
                        shell.updatePixie(pixie.id, UpdatePixieRequest(name: name))
                    }
                }
            } else {
                EditableText(text: pixie.name, label: "Edit name") { editing = .name }
                    .font(.ui(TypeSize.body, .semibold))
                    .foregroundStyle(Palette.t1)
            }
            if editing == .slug {
                InlineField(label: "Slug", initial: pixie.slug, font: .ui(TypeSize.ui)) {
                    editing = nil
                    guard let slug = $0, !slug.isEmpty, slug != pixie.slug else { return }
                    Task { refused = await shell.setPixieSlug(pixie.id, slug) }
                }
            } else {
                EditableText(text: "@\(pixie.slug)", label: "Edit slug") {
                    refused = nil
                    editing = .slug
                }
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t3)
            }
            if let refused {
                Text(refused)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(StatusTone.failed.color)
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
                .padding(.horizontal, 6)
                .padding(.vertical, 1)
                .background(hovering ? Palette.soft : .clear, in: .rounded(Radius.button))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .pointerStyle(.link)
        .onHover { hovering = $0 }
        .help(label)
        .accessibilityLabel("\(label), \(text)")
    }
}

/// A field that edits in place: Return, leaving it or a click outside it ends the edit,
/// Escape cancels it. Opening another one ends this one. `done` gets the trimmed text, or
/// nil when cancelled.
struct InlineField: View {
    let label: String
    let initial: String
    var font = Font.ui(TypeSize.ui)
    var center = true
    let done: (String?) -> Void
    @State private var text = ""
    @State private var ended = false
    @State private var id = UUID()
    @FocusState private var focused: Bool
    @Environment(Shell.self) private var shell
    @Environment(\.accentColors) private var accent

    var body: some View {
        TextField(label, text: $text)
            .textFieldStyle(.plain)
            .font(font)
            .multilineTextAlignment(center ? .center : .leading)
            .padding(.horizontal, 8)
            .frame(height: 24)
            .background(Palette.soft, in: .rounded(Radius.button))
            .overlay(
                RoundedRectangle.rounded(Radius.button).strokeBorder(accent.focus, lineWidth: 1)
            )
            .focused($focused)
            .onAppear {
                text = initial
                focused = true
                // A click outside it, or Escape wherever focus is, reaches it through the
                // shell; a field still open is ended first.
                shell.inlineEdit?.end(true)
                shell.inlineEdit = InlineEdit(id: id, frame: .zero) { keep in
                    end(keep ? text : nil)
                }
            }
            .onGeometryChange(for: CGRect.self) {
                $0.frame(in: .global)
            } action: { frame in
                if shell.inlineEdit?.id == id {
                    shell.inlineEdit?.frame = frame
                }
            }
            .onDisappear { release() }
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
        release()
        done(value?.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private func release() {
        if shell.inlineEdit?.id == id {
            shell.inlineEdit = nil
        }
    }
}

/// Mascots and colours; a click saves the choice.
private struct PixieLook: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            LazyVGrid(
                columns: Array(repeating: GridItem(.flexible(), spacing: 2), count: 5), spacing: 2
            ) {
                ForEach(Mascot.choices, id: \.self) { mascot in
                    MascotChoice(mascot: mascot, color: pixie.color, on: pixie.mascot == mascot) {
                        save(UpdatePixieRequest(mascot: mascot))
                    }
                }
            }
            HStack(spacing: 2) {
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

    var body: some View {
        Button(action: pick) {
            HoverReader { hovering in
                SpriteView(mascot: mascot, color: color, size: 20)
                    .frame(maxWidth: .infinity)
                    .frame(height: 28)
                    .background(
                        on ? Palette.selection : hovering ? Palette.soft : .clear,
                        in: .rounded(Radius.row)
                    )
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
                .frame(width: 14, height: 14)
                .padding(3)
                .overlay {
                    if on {
                        Circle().strokeBorder(Palette.t2, lineWidth: 1)
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
                .frame(width: 20, height: 20)
                .clipShape(Circle())
            Circle()
                .fill(
                    AngularGradient(
                        colors: [.red, .yellow, .green, .cyan, .blue, .purple, .red],
                        center: .center)
                )
                .frame(width: 14, height: 14)
                .padding(3)
                .overlay {
                    if on {
                        Circle().strokeBorder(Palette.t2, lineWidth: 1)
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

/// Model, Thinking, Permissions, Project files and Autonomy: a value on the right that
/// opens a menu of choices.
private struct PixieSettings: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        let agents = shell.agents
        // The model the pixie runs: its own, else the agent default's.
        let runs = pixie.model ?? agents.current.model
        let levels = agents.thinkingLevels(for: runs)
        DetailGroup {
            PickerRow(
                title: "Model",
                value: pixie.model == nil ? "Default" : agents.label(for: pixie.model)
            ) {
                ModelItems(
                    current: pixie.model,
                    defaultItem: .init(
                        detail: "The agent default, now \(agents.label(for: agents.current.model))"
                    ) { save(UpdatePixieRequest(clearsModel: true)) }
                ) { save(UpdatePixieRequest(model: $0.value)) }
            }
            PickerRow(
                title: "Thinking",
                value: levels.isEmpty ? "Not available" : pixie.effort?.label ?? "Default",
                enabled: !levels.isEmpty
            ) {
                ThinkingItems(model: runs, effort: pixie.effort, offersDefault: true) {
                    save(UpdatePixieRequest(effort: $0, clearsEffort: $0 == nil))
                }
            }
            PickerRow(title: "Permissions", value: pixie.permissionMode.label) {
                // Auto only where the model offers it, as in any chat.
                PermissionItems(
                    modes: agents.permissionModes(for: runs), current: pixie.permissionMode
                ) {
                    if let mode = $0 {
                        save(UpdatePixieRequest(permissionMode: mode))
                    }
                }
            }
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

/// Running chats at once and new chats per day, each a value with a stepper, saved at
/// once within the daemon's ranges.
private struct PixieLimitRows: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        DetailGroup {
            LimitRow(
                title: PixieLimits.runningTitle, value: pixie.maxRunning,
                range: PixieLimits.running
            ) { shell.updatePixie(pixie.id, UpdatePixieRequest(maxRunning: $0)) }
            LimitRow(
                title: PixieLimits.perDayTitle, value: pixie.maxPerDay, range: PixieLimits.perDay
            ) { shell.updatePixie(pixie.id, UpdatePixieRequest(maxPerDay: $0)) }
        }
    }
}

private struct LimitRow: View {
    let title: String
    let value: Int
    let range: ClosedRange<Int>
    let save: (Int) -> Void

    var body: some View {
        HStack(spacing: 6) {
            Text(title)
                .foregroundStyle(Palette.t1)
            Spacer(minLength: 8)
            Text(String(value))
                .monospacedDigit()
                .foregroundStyle(Palette.t2)
            Stepper(
                title,
                value: Binding(
                    get: { value },
                    set: { save(PixieLimits.clamp($0, to: range)) }),
                in: range
            )
            .labelsHidden()
            .controlSize(.mini)
        }
        .font(.ui(TypeSize.ui))
        .padding(.horizontal, 8)
        .frame(height: Metrics.rowHeight + 2)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title): \(value)")
    }
}

/// A title on the left and the value on the right; a click opens the choices.
struct PickerRow<Items: View>: View {
    let title: String
    let value: String
    var enabled = true
    @ViewBuilder let items: () -> Items
    @State private var hovering = false

    var body: some View {
        Menu {
            items()
        } label: {
            HStack(spacing: 6) {
                Text(title)
                    .foregroundStyle(Palette.t1)
                Spacer(minLength: 8)
                Text(value)
                    .foregroundStyle(Palette.t2)
                    .lineLimit(1)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(Palette.t2)
            }
            .font(.ui(TypeSize.ui))
            .padding(.horizontal, 8)
            .frame(height: Metrics.rowHeight + 2)
            .background(hovering && enabled ? Palette.soft : .clear, in: .rounded(Radius.row))
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

/// The skills it may use, as removable chips; Add, at the right of the heading, offers
/// the skills not chosen yet (B85): standalone ones, then a submenu per plugin, so a long
/// list stays short. None chosen means every skill.
private struct PixieSkillChips: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        let menu = PixieSkillMenu(
            choices: shell.pixies.skillChoices ?? [], chosen: pixie.skills)
        DetailHeading(title: "Skills") {
            HeadingAddMenu(label: "Add skill") {
                if let empty = menu.emptyText {
                    Text(empty)
                }
                ForEach(menu.standalone) { skill in
                    skillButton(skill)
                }
                if !menu.standalone.isEmpty && !menu.groups.isEmpty {
                    Divider()
                }
                ForEach(menu.groups) { group in
                    Menu(group.plugin) {
                        ForEach(group.skills) { skill in
                            skillButton(skill)
                        }
                    }
                }
            }
        }
        DetailGroup {
            FlowLayout(spacing: 6) {
                if pixie.skills.isEmpty {
                    Text("All skills")
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t3)
                        .frame(height: 22)
                }
                ForEach(pixie.skills, id: \.self) { skill in
                    HStack(spacing: 3) {
                        Text(skill)
                            .font(.mono(TypeSize.meta))
                            .foregroundStyle(Palette.t1)
                            .lineLimit(1)
                        RemoveButton(label: "Remove \(skill)") {
                            save(pixie.skills.filter { $0 != skill })
                        }
                    }
                    .padding(.leading, 7)
                    .padding(.trailing, 2)
                    .frame(height: 22)
                    .background(Palette.soft, in: .rounded(Radius.button))
                }
            }
            .padding(.horizontal, 8)
        }
        .task { try? await shell.pixies.loadSkillChoices() }
    }

    private func skillButton(_ skill: PixieSkillChoice) -> some View {
        Button(skill.shortName) { save(pixie.skills + [skill.name]) }
            .help(skill.description ?? skill.name)
    }

    private func save(_ skills: [String]) {
        shell.updatePixie(pixie.id, UpdatePixieRequest(skills: skills))
    }
}

/// "+ Add" at the right of a heading, the one place every Add of the details sits (B85).
struct HeadingAddButton: View {
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label("Add", systemImage: Icon.plus)
        }
        .buttonStyle(.nest(.plain, height: 22))
        .padding(.vertical, -4)
        .help(label)
        .accessibilityLabel(label)
    }
}

/// `HeadingAddButton` opening a menu of what to add.
struct HeadingAddMenu<Items: View>: View {
    let label: String
    @ViewBuilder let items: () -> Items

    var body: some View {
        Menu {
            items()
        } label: {
            Label("Add", systemImage: Icon.plus)
        }
        .menuStyle(.button)
        .buttonStyle(.nest(.plain, height: 22))
        .menuIndicator(.hidden)
        .fixedSize()
        .padding(.vertical, -4)
        .pointerStyle(.link)
        .help(label)
        .accessibilityLabel(label)
    }
}

/// Lays its views out in rows, wrapping to the next row when one is full.
struct FlowLayout: Layout {
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
/// no action it is shown dimmed.
struct DrillInRow: View {
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
                VStack(alignment: .leading, spacing: 1) {
                    Text(title)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t1)
                    Text(about)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if let value {
                    Text(value)
                        .font(.ui(TypeSize.ui))
                        .foregroundStyle(Palette.t2)
                        .lineLimit(1)
                        .fixedSize()
                }
                if open != nil {
                    Image(systemName: Icon.chevronRight)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(Palette.t2)
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(hovering && open != nil ? Palette.soft : .clear, in: .rounded(Radius.row))
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
                    .font(.ui(TypeSize.ui))
                    .foregroundStyle(StatusTone.failed.color)
                if let about {
                    Text(about)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t3)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(hovering ? StatusTone.failed.soft : .clear, in: .rounded(Radius.row))
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

/// The rows of one part of the details: plain rows, no fill.
struct DetailGroup<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0, content: content)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A 1 point line across the whole panel between parts of the details; the panel's
/// content is inset by `inset`, which the line undoes.
struct SectionBreak: View {
    static let inset = 6.0

    var body: some View {
        Separator()
            .padding(.horizontal, -Self.inset)
            .padding(.vertical, 8)
    }
}

/// A small grey section label, after a line across the panel unless it opens the page,
/// with its Add, if any, at the full right of the row.
struct DetailHeading<Trailing: View>: View {
    let title: String
    var divided = true
    @ViewBuilder let trailing: () -> Trailing

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if divided {
                SectionBreak()
            }
            HStack(spacing: 8) {
                Text(title)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                Spacer(minLength: 0)
                trailing()
            }
            .frame(minHeight: 14)
            .padding(.leading, 8)
            .padding(.trailing, 2)
            .padding(.top, divided ? 2 : 12)
            .padding(.bottom, 4)
        }
    }
}

extension DetailHeading where Trailing == EmptyView {
    init(title: String, divided: Bool = true) {
        self.init(title: title, divided: divided) { EmptyView() }
    }
}

/// A plain row of text in a group.
struct DetailLine: View {
    let text: String
    let dim: Bool

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.ui))
            .foregroundStyle(dim ? Palette.t3 : Palette.t1)
            .padding(.horizontal, 8)
            .frame(height: Metrics.rowHeight + 2)
    }
}

/// A short note under a group.
struct DetailNote: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.ui(TypeSize.meta))
            .foregroundStyle(Palette.t3)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 8)
            .padding(.top, 2)
    }
}

/// The pixie's artifacts on its page, newest first (B79): its reports and pages, each
/// opening in the Artifacts view, and the whole list there when there are more.
private struct PixieArtifacts: View {
    static let shown = 5
    let pixie: Pixie
    @Environment(Shell.self) private var shell

    var body: some View {
        let artifacts = shell.artifacts.list(.pixie(pixie.id))
        DetailGroup {
            if let artifacts, artifacts.isEmpty {
                DetailLine(text: "None yet", dim: true)
            }
            ForEach(artifacts?.prefix(Self.shown) ?? []) { artifact in
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    DrillInRow(
                        title: artifact.title,
                        about:
                            "\(ArtifactText.kind(artifact.kind)) · \(ArtifactText.when(artifact.updatedAt, now: context.date))",
                        value: artifact.seen ? nil : "New"
                    ) {
                        shell.openArtifact(artifact.id, version: nil, from: nil)
                    }
                }
            }
            if let artifacts, artifacts.count > Self.shown {
                DrillInRow(title: "All artifacts", about: "\(artifacts.count) saved") {
                    shell.showView(.artifacts)
                }
            }
        }
        .task(id: pixie.id) { try? await shell.artifacts.load(.pixie(pixie.id)) }
    }
}
