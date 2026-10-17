import NestKit
import SwiftUI

// A pixie's habits in its details panel (B42): the list, New habit and Edit, and each
// habit's history with its runs' transcripts.

/// The pixie's habits: name, schedule and triggers, the on switch, the last outcome and
/// the next run; Run now, History and a menu with Edit, Pause or Resume and Delete.
struct PixieHabitsPage: View {
    let pixie: Pixie
    @Environment(Shell.self) private var shell
    @State private var failure: String?
    @State private var deleting: PixieHabit?

    var body: some View {
        let habits = shell.habits.habits(of: pixie.id)
        VStack(spacing: 0) {
            PanelPageHeader(title: "Habits", back: "Details") {
                shell.pixiePanel = .details
            } trailing: {
                Button {
                    shell.pixiePanel = .habit(nil)
                } label: {
                    Label("New", systemImage: Icon.plus)
                }
                .buttonStyle(.nest(.plain))
                .help("New habit")
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if let failure {
                        DetailLine(text: failure, dim: true)
                    } else if let habits {
                        if habits.isEmpty {
                            DetailNote(text: HabitText.emptyList)
                                .padding(.top, 8)
                            Button {
                                shell.pixiePanel = .habit(nil)
                            } label: {
                                Label("New habit", systemImage: Icon.plus)
                            }
                            .buttonStyle(.nest(.primary))
                            .padding(.horizontal, 8)
                            .padding(.top, 10)
                        }
                        ForEach(habits) { habit in
                            HabitRow(habit: habit) { deleting = habit }
                            if habit.id != habits.last?.id {
                                Separator().padding(.horizontal, 8)
                            }
                        }
                        if !habits.isEmpty {
                            DetailNote(
                                text: "Habits run while Nest runs on this Mac and it is awake."
                            )
                            .padding(.top, 8)
                        }
                    }
                }
                .padding(EdgeInsets(top: 6, leading: 6, bottom: 14, trailing: 6))
            }
            .scrollIndicators(.never)
        }
        .task(id: pixie.id) {
            do {
                try await shell.habits.load(pixie.id)
                failure = nil
            } catch {
                failure = "Could not read the habits: \(Shell.describe(error))"
            }
        }
        .confirmationDialog(
            "Delete \(deleting?.name ?? "the habit")?",
            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
            titleVisibility: .visible, presenting: deleting
        ) { habit in
            Button("Delete", role: .destructive) { shell.deleteHabit(habit) }
            Button("Cancel", role: .cancel) {}
        } message: { _ in
            Text("Its history goes too. Reports it made stay in the chat.")
        }
    }
}

private struct HabitRow: View {
    let habit: PixieHabit
    let delete: () -> Void
    @Environment(Shell.self) private var shell
    @State private var hovering = false

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 8) {
                Text(habit.name)
                    .font(.ui(TypeSize.ui, .medium))
                    .foregroundStyle(habit.enabled ? Palette.t1 : Palette.t2)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: 4)
                Toggle(
                    habit.enabled ? "Pause \(habit.name)" : "Resume \(habit.name)",
                    isOn: Binding(
                        get: { habit.enabled }, set: { shell.setHabit(habit, enabled: $0) })
                )
                .toggleStyle(.switch)
                .controlSize(.mini)
                .labelsHidden()
                .pointerStyle(.link)
                .help(habit.enabled ? "On. Turn off to pause it" : "Paused. Turn on to resume it")
            }
            if !habit.summary.isEmpty {
                Text(habit.summary)
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            TimelineView(.periodic(from: .now, by: 60)) { context in
                HStack(spacing: 5) {
                    StatusMark(
                        tone: habit.lastRun?.outcome.tone ?? .done, hollow: habit.lastRun == nil,
                        slot: false)
                    Text(HabitText.lastRun(habit.lastRun, now: context.date))
                        .lineLimit(1)
                    Text("·")
                    Text(HabitText.nextRun(habit, now: context.date))
                        .lineLimit(1)
                }
                .font(.ui(TypeSize.meta))
                .monospacedDigit()
                .foregroundStyle(Palette.t3)
            }
            HStack(spacing: 2) {
                Button {
                    shell.runHabitNow(habit)
                } label: {
                    Label("Run now", systemImage: "play")
                }
                .help("Run it now, whatever the schedule and usage")
                Button {
                    shell.pixiePanel = .habitHistory(habit.id)
                } label: {
                    Label("History", systemImage: "clock")
                }
                .help("Its latest runs")
                Spacer(minLength: 0)
                RowActionsMenu(title: habit.name) {
                    Button {
                        shell.pixiePanel = .habit(habit.id)
                    } label: {
                        Label("Edit", systemImage: Icon.edit)
                    }
                    Button {
                        shell.setHabit(habit, enabled: !habit.enabled)
                    } label: {
                        Label(
                            habit.enabled ? "Pause" : "Resume",
                            systemImage: habit.enabled ? "pause" : "play")
                    }
                    Divider()
                    Button(role: .destructive, action: delete) {
                        Label("Delete", systemImage: "trash")
                    }
                }
            }
            .buttonStyle(.nest(.plain, height: 22))
            .padding(.top, 2)
            .padding(.leading, -6)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 8)
        .background(hovering ? Palette.soft : .clear, in: .rounded(Radius.row))
        .contentShape(Rectangle())
        .onHover { hovering = $0 }
        .onTapGesture(count: 2) { shell.pixiePanel = .habit(habit.id) }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(habit.name)
    }
}

/// New habit and Edit: name, instructions, schedule, triggers and the longest run.
struct HabitEditor: View {
    let pixie: Pixie
    /// The habit edited; nil for a new one.
    let habitID: String?
    @Environment(Shell.self) private var shell
    @State private var draft = HabitDraft()
    @State private var ready = false
    @State private var saving = false

    var body: some View {
        let habit = habitID.flatMap { shell.habits.habit($0, of: pixie.id) }
        VStack(spacing: 0) {
            PanelPageHeader(title: habitID == nil ? "New habit" : "Edit habit", back: "Habits") {
                shell.pixiePanel = .habits
            } trailing: {
                Button("Save") { save(habit) }
                    .buttonStyle(.nest(.primary))
                    .disabled(draft.problem != nil || saving || !ready)
                    .keyboardShortcut("s", modifiers: .command)
                    .help(draft.problem ?? "Save the habit")
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    DetailHeading(title: "Name", divided: false)
                    TextField("Morning check", text: $draft.name)
                        .textFieldStyle(.plain)
                        .font(.ui(TypeSize.ui))
                        .padding(.horizontal, 8)
                        .frame(height: 26)
                        .background(Palette.soft, in: .rounded(Radius.button))
                        .padding(.horizontal, 8)
                        .accessibilityLabel("Name")

                    DetailHeading(title: "What to check and what is worth reporting")
                    TextEditor(text: $draft.prompt)
                        .font(.ui(TypeSize.ui))
                        .scrollContentBackground(.hidden)
                        .padding(4)
                        .frame(height: 110)
                        .background(Palette.soft, in: .rounded(Radius.button))
                        .padding(.horizontal, 8)
                        .accessibilityLabel("Instructions")

                    DetailHeading(title: "Schedule")
                    ScheduleRows(draft: $draft)

                    DetailHeading(title: "Also runs when")
                    DetailGroup {
                        ForEach(HabitTrigger.choices, id: \.self) { trigger in
                            Toggle(
                                trigger.label,
                                isOn: Binding(
                                    get: { draft.triggers.contains(trigger) },
                                    set: { on in
                                        if on {
                                            draft.triggers.insert(trigger)
                                        } else {
                                            draft.triggers.remove(trigger)
                                        }
                                    })
                            )
                            .toggleStyle(.checkbox)
                            .font(.ui(TypeSize.ui))
                            .foregroundStyle(Palette.t1)
                            .padding(.horizontal, 8)
                            .frame(height: Metrics.rowHeight)
                        }
                    }
                    DetailNote(
                        text: "In chats of this pixie's projects. At most once in 5 minutes.")

                    DetailHeading(title: "Limit")
                    StepperRow(
                        title: "Longest run", value: draft.maxMinutes, unit: "min",
                        range: HabitDraft.maxMinutesRange
                    ) { draft.maxMinutes = $0 }
                    DetailNote(text: "A longer run is stopped and recorded as timed out.")

                    if let problem = draft.problem, ready {
                        Text(problem)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(StatusTone.waiting.color)
                            .padding(.horizontal, 8)
                            .padding(.top, 12)
                    }
                }
                .padding(EdgeInsets(top: 0, leading: 6, bottom: 14, trailing: 6))
            }
            .scrollIndicators(.never)
        }
        .task {
            guard !ready else { return }
            if let habitID {
                if shell.habits.habit(habitID, of: pixie.id) == nil {
                    try? await shell.habits.load(pixie.id)
                }
                guard let habit = shell.habits.habit(habitID, of: pixie.id) else {
                    shell.pixiePanel = .habits
                    return
                }
                draft = HabitDraft(habit: habit)
            }
            ready = true
        }
    }

    private func save(_ habit: PixieHabit?) {
        saving = true
        Task {
            if await shell.saveHabit(draft, editing: habit, of: pixie.id) {
                shell.pixiePanel = .habits
            }
            saving = false
        }
    }
}

/// How often it repeats, then the minute, time or day that kind needs.
private struct ScheduleRows: View {
    @Binding var draft: HabitDraft

    var body: some View {
        DetailGroup {
            PickerRow(title: "Repeats", value: draft.repeats.label) {
                ForEach(HabitDraft.Repeat.allCases, id: \.self) { kind in
                    OptionItem(title: kind.label, detail: "", checked: draft.repeats == kind) {
                        draft.repeats = kind
                    }
                }
            }
            switch draft.repeats {
            case .never:
                EmptyView()
            case .hourly:
                StepperRow(
                    title: "At minute", value: draft.hourlyMinute, unit: nil, range: 0...59,
                    format: { ":" + String(format: "%02d", $0) }
                ) { draft.hourlyMinute = $0 }
            case .daily, .weekdays, .weekly:
                if draft.repeats == .weekly {
                    PickerRow(title: "Day", value: HabitDraft.weekdayNames[draft.weekday]) {
                        ForEach(HabitDraft.weekdayNames.indices, id: \.self) { day in
                            OptionItem(
                                title: HabitDraft.weekdayNames[day], detail: "",
                                checked: draft.weekday == day
                            ) { draft.weekday = day }
                        }
                    }
                }
                HStack {
                    Text("At")
                        .foregroundStyle(Palette.t1)
                    Spacer(minLength: 8)
                    DatePicker(
                        "At",
                        selection: Binding(
                            get: { draft.date(on: .now) }, set: { draft.setTime($0) }),
                        displayedComponents: .hourAndMinute
                    )
                    .labelsHidden()
                    .datePickerStyle(.stepperField)
                    .controlSize(.small)
                    .environment(\.locale, Locale(identifier: "en_GB"))
                }
                .font(.ui(TypeSize.ui))
                .padding(.horizontal, 8)
                .frame(height: Metrics.rowHeight + 4)
            }
        }
        if draft.repeats != .never {
            DetailNote(text: "In this Mac's time. A run more than 2 hours late is skipped.")
        }
    }
}

/// A value with a stepper, such as the longest run in minutes.
private struct StepperRow: View {
    let title: String
    let value: Int
    let unit: String?
    let range: ClosedRange<Int>
    var format: (Int) -> String = { String($0) }
    let save: (Int) -> Void

    var body: some View {
        let shown = format(value) + (unit.map { " \($0)" } ?? "")
        HStack(spacing: 6) {
            Text(title)
                .foregroundStyle(Palette.t1)
            Spacer(minLength: 8)
            Text(shown)
                .monospacedDigit()
                .foregroundStyle(Palette.t2)
            Stepper(
                title,
                value: Binding(
                    get: { value }, set: { save(min(max($0, range.lowerBound), range.upperBound)) }),
                in: range
            )
            .labelsHidden()
            .controlSize(.mini)
        }
        .font(.ui(TypeSize.ui))
        .padding(.horizontal, 8)
        .frame(height: Metrics.rowHeight + 2)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(title): \(shown)")
    }
}

/// A habit's latest runs, newest first: outcome, start, length and report title, with
/// Open transcript for runs that had a session.
struct HabitHistoryPage: View {
    let pixie: Pixie
    let habitID: String
    @Environment(Shell.self) private var shell
    @State private var failure: String?

    var body: some View {
        let habit = shell.habits.habit(habitID, of: pixie.id)
        let runs = shell.habits.runs(of: habitID)
        VStack(spacing: 0) {
            PanelPageHeader(title: habit?.name ?? "History", back: "Habits") {
                shell.pixiePanel = .habits
            } trailing: {
                if let habit {
                    Button {
                        shell.runHabitNow(habit)
                    } label: {
                        Label("Run now", systemImage: "play")
                    }
                    .buttonStyle(.nest(.plain))
                }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if let failure {
                        DetailLine(text: failure, dim: true)
                    } else if let runs {
                        if runs.isEmpty {
                            DetailNote(text: HabitText.emptyHistory).padding(.top, 8)
                        }
                        ForEach(runs) { run in
                            RunRow(run: run)
                        }
                    }
                }
                .padding(EdgeInsets(top: 6, leading: 6, bottom: 14, trailing: 6))
            }
            .scrollIndicators(.never)
        }
        .task(id: habitID) {
            do {
                if habit == nil {
                    try await shell.habits.load(pixie.id)
                }
                try await shell.habits.loadRuns(habitID, in: pixie.id)
                failure = nil
            } catch {
                failure = "Could not read the history: \(Shell.describe(error))"
            }
        }
    }
}

private struct RunRow: View {
    let run: HabitRun
    @Environment(Shell.self) private var shell

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            let details = [
                HabitText.duration(run, now: context.date), run.reportTitle ?? run.reason,
            ]
            .compactMap { $0 }
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    StatusMark(tone: run.outcome.tone)
                    Text(run.outcome.label)
                        .font(.ui(TypeSize.ui, .medium))
                        .foregroundStyle(Palette.t1)
                    Spacer(minLength: 4)
                    Text(HabitText.started(run, now: context.date))
                        .font(.ui(TypeSize.meta))
                        .monospacedDigit()
                        .foregroundStyle(Palette.t3)
                }
                if !details.isEmpty {
                    Text(details.joined(separator: " · "))
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.t2)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
                if let session = run.sessionID {
                    Button("Open transcript") { shell.openHabitRun(session) }
                        .buttonStyle(.plain)
                        .pointerStyle(.link)
                        .font(.ui(TypeSize.meta))
                        .foregroundStyle(Palette.link)
                        .help("This run's chat, read-only")
                }
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .accessibilityElement(children: .contain)
    }
}

/// A habit run's chat, read-only: its transcript without a composer.
struct HabitRunSheet: View {
    let session: String
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 1) {
                    Text("Habit run")
                        .font(.ui(TypeSize.body, .semibold))
                    if let title = shell.sessions.session(session)?.title {
                        Text(title)
                            .font(.ui(TypeSize.meta))
                            .foregroundStyle(Palette.t3)
                            .lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Text("Read-only")
                    .font(.ui(TypeSize.meta))
                    .foregroundStyle(Palette.t3)
                Button {
                    shell.close()
                } label: {
                    Image(systemName: Icon.close).font(.system(size: 10, weight: .medium))
                }
                .buttonStyle(.nest(.plain, iconOnly: true))
                .foregroundStyle(Palette.t3)
                .accessibilityLabel("Close the habit run")
            }
            .padding(.leading, 18)
            .padding(.trailing, 10)
            .frame(height: 46)
            .overlay(alignment: .bottom) { Separator() }
            TranscriptView(chat: session)
                .id(session)
        }
        .foregroundStyle(Palette.t1)
        .frame(width: 720, height: 600)
        .sheetSurface()
        .task(id: session) {
            if shell.sessions.session(session) == nil {
                try? await shell.sessions.fetch(session)
            }
        }
    }
}
