#if DEBUG
    import NestKit

    /// Settings > Features' sample catalog (B103): the real catalog's entries, with four of
    /// them new on this device.
    enum SampleFeatures {
        static var catalog: FeaturesCatalog {
            let groups = [
                group(
                    "around", "Getting around",
                    [
                        Feature(
                            id: "needs-you", name: "Needs you",
                            text:
                                "Everything waiting on you in one list: approvals, questions, reviews and merges.",
                            place: "Right panel", added: "2026-10-17",
                            block: "B77"),
                        Feature(
                            id: "split-workspace", name: "Split workspace",
                            text: "Up to four chats, terminals, browsers or pixies side by side.",
                            place: "Workspace", added: "2026-10-14",
                            block: "B36"),
                        Feature(
                            id: "focus-dim", name: "Focus dim",
                            text:
                                "Panes you are not using go darker, so the one you work in stands out.",
                            place: "Workspace", added: "2026-10-18",
                            block: "B93"),
                        Feature(
                            id: "terminal-browser-panes", name: "Terminal and browser panes",
                            text:
                                "A terminal in the chat's folder and a browser for your local servers, next to the chat.",
                            place: "Project menu", added: "2026-10-07",
                            block: "B25"),
                        Feature(
                            id: "run-in-terminal", name: "Run in terminal",
                            text:
                                "A shell command in a chat runs in a terminal in that chat's folder with one click.",
                            place: "Code blocks", added: "2026-10-15",
                            block: "B60"),
                        Feature(
                            id: "board", name: "Board",
                            text:
                                "Every chat in the project as a card, sorted by what it is doing.",
                            place: "Status bar", added: "2026-10-14",
                            block: "B39"),
                        Feature(
                            id: "goals", name: "Goals",
                            text: "The plan of each working chat as a live checklist.",
                            place: "Right panel", added: "2026-10-16",
                            block: "B47"),
                        Feature(
                            id: "chat-helpers", name: "Each chat's helpers",
                            text:
                                "Under every chat, the pixies it called and the subagents running for it.",
                            place: "Sidebar", added: "2026-10-16",
                            block: "B46"),
                        Feature(
                            id: "outside-chats", name: "Chats from outside Nest",
                            text:
                                "Agent chats started in a terminal or another app show up here, and you can continue them.",
                            place: "Sidebar", added: "2026-10-07",
                            block: "B21"),
                        Feature(
                            id: "folding-sidebars", name: "Sidebars that fold",
                            text:
                                "Fold the sidebar and the right panel to thin strips that still show each chat's status.",
                            place: "Status bar", added: "2026-10-17",
                            block: "B83"),
                        Feature(
                            id: "project-tabs", name: "Project tabs",
                            text:
                                "Every project in its own tab. Drag to reorder, jump with a shortcut.",
                            place: "⌘1 to ⌘9", added: "2026-10-16",
                            block: "B45"),
                        Feature(
                            id: "open-in-tools", name: "Open in your tools",
                            text: "Open a project in your editor, Finder or Terminal.",
                            place: "Project menu", added: "2026-10-06",
                            block: "B20"),
                        Feature(
                            id: "search-commands", name: "Search and commands",
                            text: "Find any chat or message, or run any command, from one box.",
                            place: "⌘K", added: "2026-10-07",
                            block: "B09"),
                    ]),
                group(
                    "chats", "Chats",
                    [
                        Feature(
                            id: "composer-shortcuts", name: "Composer shortcuts",
                            text:
                                "`/` for commands and skills, `@` for files and pixies, `!` to run a shell command, `#` to save a note to your instructions.",
                            place: "Composer", added: "2026-10-15",
                            block: "B59"),
                        Feature(
                            id: "talk-while-working", name: "Talk while it works",
                            text:
                                "A message you send while the agent is working reaches it at its next step.",
                            place: "Composer", added: "2026-10-15",
                            block: "B59"),
                        Feature(
                            id: "rewind-fork", name: "Rewind and fork",
                            text:
                                "Go back to before any of your messages, or start a new chat from that point.",
                            place: "Your message's menu", added: "2026-10-15",
                            block: "B59"),
                        Feature(
                            id: "limit-resume", name: "Picks up after the limit",
                            text:
                                "A chat stopped by a usage limit continues by itself once the limit resets.",
                            place: "Automatic", added: "2026-10-17",
                            block: "B78"),
                        Feature(
                            id: "stuck-chats", name: "Stuck chats",
                            text:
                                "A chat that stalls or repeats itself is flagged, with a nudge to get it moving.",
                            place: "Needs you", added: "2026-10-06",
                            block: "B20"),
                    ]),
                group(
                    "git", "Worktrees and git",
                    [
                        Feature(
                            id: "worktree-per-chat", name: "A worktree per chat",
                            text:
                                "A chat can work in its own copy of the project on its own branch, so several can run at once.",
                            place: "New chat", added: "2026-10-15",
                            block: "B55"),
                        Feature(
                            id: "branch-map", name: "Branch map",
                            text:
                                "Your branches and worktrees drawn as a tree. Start a chat on any of them.",
                            place: "Sidebar", added: "2026-10-21",
                            block: "B96", isNew: true),
                        Feature(
                            id: "review", name: "Review before it lands",
                            text:
                                "Changes wait in a diff. Approve commits exactly what you saw and can open a pull request.",
                            place: "Above the composer", added: "2026-10-15",
                            block: "B57"),
                        Feature(
                            id: "issues-to-chats", name: "Issues become chats",
                            text:
                                "Start a chat from an open issue, with its own branch and a pull request that closes it.",
                            place: "Start screen", added: "2026-10-21",
                            block: "B101", isNew: true),
                        Feature(
                            id: "feedback-to-agent", name: "Feedback back to the agent",
                            text:
                                "Failed checks and reviewers' comments go to the chat in one click.",
                            place: "Needs you", added: "2026-10-14", changed: "2026-10-21",
                            block: "B101", isNew: true),
                    ]),
                group(
                    "pixies", "Pixies",
                    [
                        Feature(
                            id: "pixies", name: "Pixies",
                            text:
                                "Agents you keep, each with its own instructions, model and look.",
                            place: "Pixies tab", added: "2026-10-14",
                            block: "B35"),
                        Feature(
                            id: "pixies-workspace", name: "Pixies workspace",
                            text:
                                "Open up to four pixies side by side, with their details beside them.",
                            place: "Pixies tab", added: "2026-10-14",
                            block: "B37"),
                        Feature(
                            id: "pixie-memory", name: "Memory",
                            text:
                                "A pixie remembers facts and notes between runs, and you can edit them.",
                            place: "Pixie details", added: "2026-10-14",
                            block: "B35"),
                        Feature(
                            id: "pixie-fresh-runs", name: "Never runs out of room",
                            text:
                                "Each run starts fresh with the pixie's memory and recent messages, so a long chat never fills up.",
                            place: "Automatic", added: "2026-10-14",
                            block: "B35"),
                        Feature(
                            id: "pixie-calls", name: "Call with @",
                            text:
                                "Hand part of any chat to a pixie. Calling it again picks up where it left off.",
                            place: "Composer", added: "2026-10-14",
                            block: "B40"),
                        Feature(
                            id: "pixie-teams", name: "Teams",
                            text: "Call a team and its leader splits the work among its pixies.",
                            place: "Pixies tab", added: "2026-10-14", changed: "2026-10-16",
                            block: "B70"),
                        Feature(
                            id: "pixie-project-access", name: "Project access",
                            text:
                                "Let a pixie edit your projects, only read them, or stay in its own folder.",
                            place: "Pixie details", added: "2026-10-15",
                            block: "B41"),
                        Feature(
                            id: "pixie-skills", name: "Skills",
                            text: "Give a pixie all your skills or only a chosen few.",
                            place: "Pixie details", added: "2026-10-17",
                            block: "B85"),
                        Feature(
                            id: "pixie-autonomy", name: "Autonomy",
                            text:
                                "Let a pixie watch, message, start or answer chats, within limits you set.",
                            place: "Pixie details", added: "2026-10-15",
                            block: "B41"),
                        Feature(
                            id: "pixie-started-chats", name: "Chats it starts",
                            text:
                                "A pixie can start chats in their own worktree, reviewed as usual, and tells you how they went.",
                            place: "Pixie chat", added: "2026-10-15",
                            block: "B41"),
                        Feature(
                            id: "pixie-activity", name: "Activity",
                            text: "Everything a pixie did in Nest, listed in one place.",
                            place: "Pixie details", added: "2026-10-15",
                            block: "B41"),
                        Feature(
                            id: "pixie-habits", name: "Habits",
                            text:
                                "Pixies run checks on a schedule, or when a chat gets stuck, fails or is ready.",
                            place: "Pixie details", added: "2026-10-15",
                            block: "B42"),
                        Feature(
                            id: "pixie-reports", name: "Reports",
                            text:
                                "A pixie reports what it found. The ones that need you reach Needs you and your phone.",
                            place: "Pixie chat", added: "2026-10-15",
                            block: "B42"),
                        Feature(
                            id: "pixie-replies", name: "Reply buttons",
                            text:
                                "A pixie can offer answers to tap, or suggest a habit you start with one tap.",
                            place: "Pixie chat", added: "2026-10-15",
                            block: "B42"),
                        Feature(
                            id: "pixie-templates", name: "Templates and copies",
                            text: "Start from a ready-made pixie, or copy one with its memory.",
                            place: "Pixies tab", added: "2026-10-14",
                            block: "B40"),
                        Feature(
                            id: "pixie-sprites", name: "Working sprites",
                            text: "A pixie's sprite hops while it works, wherever it shows.",
                            place: "Everywhere", added: "2026-10-16",
                            block: "B48"),
                    ]),
                group(
                    "artifacts", "Artifacts",
                    [
                        Feature(
                            id: "artifacts", name: "Artifacts",
                            text:
                                "Reports, plans, slides and mockups saved as pages with versions, kept out of your repo.",
                            place: "Artifacts view", added: "2026-10-17",
                            block: "B82"),
                        Feature(
                            id: "living-pages", name: "Living pages",
                            text:
                                "Pages remember what you enter, on every device, and can ask the agent small questions.",
                            place: "Artifacts view", added: "2026-10-19",
                            block: "B88"),
                    ]),
                group(
                    "engines", "Engines and devices",
                    [
                        Feature(
                            id: "several-engines", name: "Several engines",
                            text:
                                "Pick any signed-in engine for a chat or a pixie, from one model menu.",
                            place: "Model menu", added: "2026-10-20",
                            block: "B91"),
                        Feature(
                            id: "several-accounts", name: "Several accounts",
                            text:
                                "Add more subscriptions for an engine and choose which one is used.",
                            place: "Settings › Accounts", added: "2026-10-21",
                            block: "B98", isNew: true),
                        Feature(
                            id: "shared-setup", name: "One shared setup",
                            text:
                                "Instructions, skills and tool servers are shared by every engine.",
                            place: "Settings › Configuration", added: "2026-10-20",
                            block: "B97"),
                        Feature(
                            id: "iphone", name: "Your iPhone",
                            text:
                                "Nest on your phone over your private network, with push notifications.",
                            place: "Settings › Devices", added: "2026-10-07",
                            block: "B10"),
                    ]),
            ]
            return FeaturesCatalog(
                groups: groups, newCount: groups.reduce(0) { $0 + $1.newCount })
        }

        /// The catalog once this device has shown `shown`: those are not new any more.
        static func catalog(shown: Set<String>) -> FeaturesCatalog {
            var catalog = catalog
            for group in catalog.groups.indices {
                for index in catalog.groups[group].features.indices
                where shown.contains(catalog.groups[group].features[index].id) {
                    catalog.groups[group].features[index].isNew = false
                }
            }
            catalog.newCount = catalog.groups.reduce(0) { $0 + $1.newCount }
            return catalog
        }

        private static func group(_ id: String, _ name: String, _ features: [Feature])
            -> FeatureGroup
        {
            FeatureGroup(id: id, name: name, features: features)
        }
    }
#endif
