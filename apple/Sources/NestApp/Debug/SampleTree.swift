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

        private static func text(_ value: String) -> [String: Any] {
            ["type": "text", "text": value]
        }

        private static func use(_ id: String, _ name: String, _ input: [String: Any])
            -> [String: Any]
        {
            ["type": "tool_use", "id": id, "name": name, "input": input]
        }

        private static func result(_ id: String, _ content: String) -> [String: Any] {
            ["type": "tool_result", "tool_use_id": id, "content": content, "is_error": false]
        }

        private static func message(_ event: Int, at date: Date, _ blocks: [[String: Any]])
            -> [String: Any]
        {
            ["event_id": event, "ts": SampleData.iso(date), "blocks": blocks]
        }

        /// Reviewer's two calls in c2, newest first.
        static func reviewerWork(now: Date) -> [PixieCallWork] {
            let groups = groups(now: now)
            let calls = groups["c2"]![0].calls
            let second: [String: Any] = [
                "prompt": "Check the DOI links you suggested now render on /publications",
                "messages": [
                    message(
                        801, at: now - 230,
                        [
                            text("Picking up where I left off: the links should be in place now."),
                            use("rr3", "Read", ["file_path": "app/publications/page.tsx"]),
                        ]),
                    message(802, at: now - 225, [result("rr3", "line\nline\nline")]),
                    message(
                        803, at: now - 220,
                        [use("rr4", "Bash", ["command": "npm test -- publications"])]),
                    message(804, at: now - 200, [result("rr4", "Tests: 6 passed")]),
                ],
                "report": "The DOI links render and open doi.org. Tests pass.",
            ]
            let first: [String: Any] = [
                "prompt": "Review the BibTeX parser and the publications page",
                "messages": [
                    message(
                        701, at: now - 710,
                        [
                            text("Reading the parser first."),
                            use("rr1", "Read", ["file_path": "lib/bibtex.ts"]),
                            use("rr2", "Grep", ["pattern": "doi", "path": "content/refs.bib"]),
                        ]),
                    message(
                        702, at: now - 700,
                        [result("rr1", "line\nline"), result("rr2", "9 matches")]),
                ],
                "report":
                    "Two issues. `parseBib` drops the `doi` field, and entries without a year sort first. Otherwise it reads well.",
            ]
            return [
                try! merge(calls[0], second), try! merge(calls[1], first),
            ]
        }

        private static func merge(_ call: ChatPixieCall, _ work: [String: Any]) throws
            -> PixieCallWork
        {
            var object = work
            object["id"] = call.id
            object["pixie_id"] = call.pixieID
            object["tool_use_id"] = call.toolUseID
            object["agent_id"] = call.agentID as Any? ?? NSNull()
            object["state"] = call.state.rawValue
            object["continued"] = call.continued
            object["started_at"] = SampleData.iso(call.startedAt)
            object["finished_at"] = call.finishedAt.map(SampleData.iso) as Any? ?? NSNull()
            return try SampleData.decode(object)
        }

        /// Explore's transcript in c2, still running.
        static func exploreWork(now: Date) -> AgentWork {
            try! SampleData.decode([
                "tool_use_id": "toolu_explore",
                "prompt":
                    "Find which entries in content/refs.bib carry a DOI, and list them by key.",
                "messages": [
                    message(
                        901, at: now - 60,
                        [
                            text("I'll look for the bib file first."),
                            use("ex1", "Glob", ["pattern": "content/**/*.bib"]),
                        ]),
                    message(902, at: now - 55, [result("ex1", "content/refs.bib")]),
                    message(
                        903, at: now - 50,
                        [use("ex2", "Grep", ["pattern": "doi", "path": "content/refs.bib"])]),
                ],
                "report": NSNull(),
            ])
        }
    }
#endif
