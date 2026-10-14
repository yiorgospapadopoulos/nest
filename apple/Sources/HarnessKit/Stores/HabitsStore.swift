import Foundation
import Observation

/// The habits of the pixies whose Habits page or cards were shown, and the run history
/// of the habits whose History was opened (B42). Events keep both current.
@MainActor @Observable
public final class HabitsStore {
    /// Habits by pixie id, oldest first; a pixie is missing until its habits are read.
    private var lists: [String: [PixieHabit]] = [:]
    /// Runs by habit id, newest first; a habit is missing until its history is read.
    private var history: [String: [HabitRun]] = [:]

    let api: any HarnessAPI

    public init(api: any HarnessAPI) {
        self.api = api
    }

    /// The pixie's habits, or nil until they are read (`load`).
    public func habits(of pixie: String) -> [PixieHabit]? {
        lists[pixie]
    }

    public func habit(_ id: String, of pixie: String) -> PixieHabit? {
        lists[pixie]?.first { $0.id == id }
    }

    /// The habit's runs, or nil until they are read (`loadRuns`).
    public func runs(of habit: String) -> [HabitRun]? {
        history[habit]
    }

    public func load(_ pixie: String) async throws {
        lists[pixie] = Self.sorted(try await api.pixieHabits(pixie))
    }

    public func loadRuns(_ habit: String, in pixie: String) async throws {
        history[habit] = try await api.habitRuns(pixie, habit)
    }

    public func apply(_ event: Event) {
        switch event.body {
        case .habitUpdated(let habit): receive(habit)
        case .habitDeleted(let id, let pixie): forget(id, in: pixie)
        case .habitRunUpdated(let run): receive(run)
        case .pixieDeleted(let pixie):
            for habit in lists[pixie] ?? [] {
                history[habit.id] = nil
            }
            lists[pixie] = nil
        default: break
        }
    }

    // MARK: Actions

    @discardableResult
    public func create(in pixie: String, _ request: CreateHabitRequest) async throws
        -> PixieHabit
    {
        let habit = try await api.createHabit(pixie, request)
        receive(habit)
        return habit
    }

    @discardableResult
    public func update(_ id: String, in pixie: String, _ request: UpdateHabitRequest)
        async throws -> PixieHabit
    {
        let habit = try await api.updateHabit(pixie, id, request)
        receive(habit)
        return habit
    }

    /// Pause (false) or Resume (true).
    public func setEnabled(_ id: String, in pixie: String, _ enabled: Bool) async throws {
        try await update(id, in: pixie, UpdateHabitRequest(enabled: enabled))
    }

    public func delete(_ id: String, in pixie: String) async throws {
        try await api.deleteHabit(pixie, id)
        forget(id, in: pixie)
    }

    /// Queues a run now; it shows at the top of the history.
    @discardableResult
    public func runNow(_ id: String, in pixie: String) async throws -> HabitRun {
        let run = try await api.runHabit(pixie, id)
        receive(run)
        return run
    }

    // MARK: Events

    /// Kept only for pixies whose habits were read; an older copy is ignored.
    private func receive(_ habit: PixieHabit) {
        guard var list = lists[habit.pixieID] else { return }
        if let index = list.firstIndex(where: { $0.id == habit.id }) {
            guard list[index].updatedAt <= habit.updatedAt else { return }
            list[index] = habit
        } else {
            list.append(habit)
        }
        lists[habit.pixieID] = Self.sorted(list)
    }

    /// A run joins its habit's history, and once it has started it is the habit's last run.
    private func receive(_ run: HabitRun) {
        if var runs = history[run.habitID] {
            if let index = runs.firstIndex(where: { $0.id == run.id }) {
                runs[index] = run
            } else {
                runs.insert(run, at: 0)
            }
            history[run.habitID] = runs
        }
        guard var list = lists[run.pixieID],
            let index = list.firstIndex(where: { $0.id == run.habitID })
        else { return }
        if run.outcome != .queued || list[index].lastRun?.id == run.id {
            list[index].lastRun = run
            lists[run.pixieID] = list
        }
    }

    private func forget(_ id: String, in pixie: String) {
        lists[pixie]?.removeAll { $0.id == id }
        history[id] = nil
    }

    private static func sorted(_ list: [PixieHabit]) -> [PixieHabit] {
        list.sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }
    }
}
