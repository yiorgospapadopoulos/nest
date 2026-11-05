#if DEBUG
    import Foundation
    import NestKit

    /// Each chat's pixies and their work for the sample daemon (B46): in "Update
    /// publications from BibTeX" (c2), Reviewer answered twice (the second call continued
    /// the first) and Watcher works; the snapshots add a team.
    enum SampleTree {
        static func call(
            _ id: String, pixie: String, tool: String, agent: String?, state: String,
            continued: Bool = false, started: Date, finished: Date? = nil
        ) -> [String: Any] {
            [
                "id": id, "pixie_id": pixie, "tool_use_id": tool,
                "agent_id": agent as Any? ?? NSNull(), "state": state, "continued": continued,
                "started_at": SampleData.iso(started),
                "finished_at": finished.map(SampleData.iso) as Any? ?? NSNull(),
            ]
        }

        static func pixie(_ id: String, state: String, calls: [[String: Any]]) -> [String: Any] {
            [
                "kind": "pixie", "pixie_id": id, "team_id": NSNull(), "state": state,
                "members": [], "calls": calls,
            ]
        }

        static func team(
            _ id: String, state: String, members: [(String, Bool, String?)],
            calls: [[String: Any]]
        ) -> [String: Any] {
            [
                "kind": "team", "pixie_id": NSNull(), "team_id": id, "state": state,
                "members": members.map { pixie, leader, state in
                    ["pixie_id": pixie, "leader": leader, "state": state as Any? ?? NSNull()]
                },
                "calls": calls,
            ]
        }

        static func groups(now: Date) -> [String: [ChatPixieEntry]] {
            let reviewer = [
                call(
                    "k2", pixie: "reviewer", tool: "rv2", agent: "a7d8f3a2", state: "done",
                    continued: true, started: now - 240, finished: now - 180),
                call(
                    "k1", pixie: "reviewer", tool: "rv1", agent: "a7d8f3a2", state: "done",
                    started: now - 720, finished: now - 600),
            ]
            let watcher = [
                call(
                    "k3", pixie: "watcher", tool: "wt1", agent: "b19c", state: "running",
                    started: now - 90)
            ]
            return [
                "c2": try! SampleData.decode([
                    pixie("reviewer", state: "done", calls: reviewer),
                    pixie("watcher", state: "running", calls: watcher),
                ])
            ]
        }
    }
#endif
