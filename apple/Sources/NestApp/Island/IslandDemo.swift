#if DEBUG
    import AppKit
    import NestKit

    /// Made-up pixies for the island's snapshots and its demo.
    @MainActor
    enum IslandSamples {
        static let solos: [(id: String, name: String, mascot: String, color: String)] = [
            ("brook", "Brook", "brook", "#12A594"), ("firefly", "Firefly", "firefly", "#FFC53D"),
            ("moth", "Moth", "moth", "#D6409F"), ("dragonfly", "Dragonfly", "dragonfly", "#E2A16F"),
            ("frost", "Frost", "frost", "#8D8D8D"), ("bluebell", "Bluebell", "bluebell", "#0090FF"),
            ("rose", "Rose", "rose", "#E5484D"), ("sprig", "Sprig", "sprig", "#46A758"),
            ("star", "Star", "star", "#F76B15"),
        ]

        static func pixie(_ id: String) -> Pixie {
            let sample = solos.first { $0.id == id } ?? solos[0]
            let now = SampleData.iso(Date())
            return try! SampleData.decode([
                "id": sample.id, "slug": sample.id, "name": sample.name, "mascot": sample.mascot,
                "color": sample.color, "model": NSNull(), "effort": NSNull(),
                "permission_mode": "default", "autonomy": "observe", "project_access": "read",
                "skills": [String](), "can_call": [String](), "hidden": false, "position": 0,
                "chat_session_id": NSNull(), "max_running": 2, "max_per_day": 5,
                "unread_action_reports": 0, "created_at": now, "updated_at": now,
            ])
        }

        static func team(_ name: String, members: [String], working: Bool) -> IslandFigure {
            let now = SampleData.iso(Date())
            let team: PixieTeam = try! SampleData.decode([
                "id": "team-\(name)", "name": name, "handle": name.lowercased(),
                "leader_id": members[0], "position": 0, "created_at": now, "updated_at": now,
            ])
            let cells = TeamIcon.fill(members.map(pixie)).enumerated().map {
                TeamIconCell(pixie: $1, working: working, index: $0)
            }
            return .team(team, color: pixie(members[0]).color, cells: cells)
        }

        static func entry(
            _ id: String, _ status: IslandStatus, since: Date, activity: String? = nil,
            team: [String]? = nil
        ) -> IslandEntry {
            let figure =
                team.map { Self.team(id, members: $0, working: status == .working) }
                ?? .pixie(pixie(id))
            let label =
                switch figure {
                case .pixie(let pixie): pixie.name
                case .team(let team, _, _): team.name
                }
            let line =
                activity
                ?? (status == .working
                    ? "Editing auth.ts" : status == .done ? "Finished" : "Wants to run npm install")
            return IslandEntry(
                id: id, figure: figure, label: label, place: .chat(session: id, repo: "todo-ui"),
                approvalID: status == .needsYou || status == .seen ? "a-\(id)" : nil,
                status: status, since: since, activity: line)
        }

        /// A state from entries in order, as `IslandState.make` would sort them.
        static func state(
            _ entries: [IslandEntry], nightshade: NightshadeMode = .idle, pill: Bool = false
        ) -> IslandState {
            let list = entries.sorted { $0.since > $1.since }
            let left = list.filter { $0.status == .working }
            return IslandState(
                left: left, right: list.filter { $0.status != .working }, list: list,
                nightshade: left.isEmpty ? nightshade : nil,
                restingBluebell: pill && entries.isEmpty, isHidden: false)
        }
    }

    /// `--island-demo [story|idle|asleep|working|done|needs|crowd]`: only the island runs, on
    /// sample data and no daemon, playing the mockup's story with made-up pixies or holding
    /// one state, so it can be looked at and its CPU use measured.
    @MainActor
    final class IslandDemo {
        enum Mode: String {
            case story, idle, asleep, working, done, needs
            /// Eight done pixies: three show, the rest in the +N.
            case crowd
        }

        private struct NoEvents: EventSource {
            func updates() -> AsyncThrowingStream<EventStreamUpdate, any Error> {
                AsyncThrowingStream { _ in }
            }
        }

        /// Runs the island alone and never returns, when the flag asks for it.
        static func runIfRequested() {
            guard isRequested else { return }
            let app = NSApplication.shared
            app.setActivationPolicy(.accessory)
            let suite = "local.nest.island-demo"
            let defaults = UserDefaults(suiteName: suite)!
            defaults.removePersistentDomain(forName: suite)
            let model = AppModel(
                api: SampleAPI(), events: NoEvents(),
                preferences: UserDefaultsStore(defaults: defaults))
            let island = IslandController(shell: Shell(model: model))
            island.start()
            app.run()
            exit(0)
        }

        static var mode: Mode {
            let arguments = CommandLine.arguments
            guard let index = arguments.firstIndex(of: "--island-demo"),
                index + 1 < arguments.count
            else { return .story }
            return Mode(rawValue: arguments[index + 1]) ?? .story
        }

        private struct Agent {
            var id: String
            var team: [String]?
            var status: IslandStatus
            var since: Date
        }

        private var agents: [Agent] = []
        private var step = 0
        private var timer: Timer?
        private var lastWork = Date()
        var onChange: () -> Void = {}
        /// Asks the island to open its list, as the story's "show list" step does.
        var onPin: () -> Void = {}

        static var isRequested: Bool { CommandLine.arguments.contains("--island-demo") }

        func start() {
            switch Self.mode {
            case .story: next()
            case .idle, .asleep: lastWork = Self.mode == .idle ? .distantFuture : .distantPast
            case .working: start("brook")
            case .done: start("brook", status: .done)
            case .needs: start("brook", status: .needsYou)
            case .crowd:
                // Apart, so their happy hops fall at different moments.
                for (index, sample) in IslandSamples.solos.prefix(8).enumerated() {
                    Timer.scheduledTimer(withTimeInterval: Double(index) * 0.9, repeats: false) {
                        [weak self] _ in
                        MainActor.assumeIsolated {
                            self?.start(sample.id, status: .done)
                            self?.onChange()
                        }
                    }
                }
            }
            onChange()
        }

        func stop() {
            timer?.invalidate()
            timer = nil
        }

        func state(pill: Bool) -> IslandState {
            let entries = agents.map {
                IslandSamples.entry($0.id, $0.status, since: $0.since, team: $0.team)
            }
            let asleep =
                !agents.contains { $0.status == .working }
                && Date().timeIntervalSince(lastWork) > 9
            return IslandSamples.state(entries, nightshade: asleep ? .asleep : .idle, pill: pill)
        }

        /// A click: a done pixie leaves, one that needs the user turns calm.
        func click(_ target: IslandTarget) {
            guard case .entry(let entry) = target,
                let index = agents.firstIndex(where: { $0.id == entry.id })
            else { return }
            switch agents[index].status {
            case .done, .failed, .interrupted: agents.remove(at: index)
            case .needsYou:
                agents[index].status = .seen
                agents[index].since = Date()
            default: break
            }
            onChange()
        }

        private func next() {
            let steps: [(() -> Void, Double)] = [
                ({ self.agents = [] }, 2.6), ({ self.start("brook") }, 2),
                ({ self.start("Docs team", team: ["bluebell", "rose", "sprig", "star"]) }, 2),
                ({ self.start("firefly") }, 2), ({ self.start("moth") }, 2.4),
                ({ self.set("brook", .done) }, 2.6), ({ self.set("Docs team", .needsYou) }, 2.8),
                ({ self.set("firefly", .done) }, 2.6), ({ self.onPin() }, 3.8),
                ({ self.set("Docs team", .seen) }, 4.2), ({ self.remove("brook") }, 2),
                ({ self.set("Docs team", .done) }, 2.8), ({ self.remove("firefly") }, 1.8),
                ({ self.remove("Docs team") }, 2), ({ self.set("moth", .done) }, 2.6),
                ({ self.remove("moth") }, 12),
            ]
            let (action, delay) = steps[step % steps.count]
            step += 1
            action()
            if agents.contains(where: { $0.status == .working }) { lastWork = Date() }
            onChange()
            timer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) {
                [weak self] _ in
                MainActor.assumeIsolated { self?.next() }
            }
        }

        private func start(
            _ id: String, team: [String]? = nil, status: IslandStatus = .working
        ) {
            agents.append(Agent(id: id, team: team, status: status, since: Date()))
        }

        private func set(_ id: String, _ status: IslandStatus) {
            guard let index = agents.firstIndex(where: { $0.id == id }) else { return }
            agents[index].status = status
            agents[index].since = Date()
            lastWork = Date()
        }

        private func remove(_ id: String) {
            agents.removeAll { $0.id == id }
        }
    }
#endif
