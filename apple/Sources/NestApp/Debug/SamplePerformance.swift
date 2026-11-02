#if DEBUG
    import Foundation
    import NestKit

    /// Settings > Performance's sample results (B115): a finished run with a previous one,
    /// a section that failed and the Mac app's section not measured yet.
    enum SamplePerformance {
        static func view(now: Date) -> PerfView {
            let ran = now.addingTimeInterval(-600)
            return PerfView(
                lastRun: PerfLastRun(finishedAt: ran, durationMs: 102_000),
                cards: [
                    metric(
                        "context_total", "Context cost of a new chat", 39_700, 38_500, .tokens,
                        "39.7k", "38.5k", "▲ 1.2k", .worse, sub: "20% of the window",
                        parts: [
                            PerfPart(label: "System prompt", value: 23_000, text: "23k"),
                            PerfPart(label: "Tools", value: 5_200, text: "5.2k"),
                            PerfPart(label: "MCP tools", value: 2_800, text: "2.8k"),
                            PerfPart(label: "Nest tools", value: 6_200, text: "6.2k"),
                        ]),
                    metric(
                        "cache_hit", "Cache hit rate", 91, 97, .percent, "91%", "97%", "▼ 6%",
                        .worse,
                        parts: [
                            PerfPart(label: "Claude", value: 93, text: "93%"),
                            PerfPart(label: "Codex", value: 74, text: "74%"),
                        ]),
                    metric(
                        "first_reply", "First reply", 2_400, 2_400, .ms, "2.4 s", "2.4 s", "0%",
                        .same,
                        parts: [
                            PerfPart(label: "Typical turn", value: 38_000, text: "38 s"),
                            PerfPart(label: "Slowest turn", value: 372_000, text: "6 min 12 s"),
                        ]),
                    metric(
                        "biggest_chat", "Biggest chat opens", 1_800, 2_400, .ms, "1.8 s", "2.4 s",
                        "▼ 25%", .better, sub: "2.1 MB",
                        parts: [
                            PerfPart(label: "Open the app", value: 420, text: "0.42 s"),
                            PerfPart(label: "Slow phone network", value: 6_200, text: "6.2 s"),
                        ]),
                ],
                sections: [
                    PerfSection(
                        id: "context", title: "Context cost", live: true, ranAt: ran,
                        metrics: [
                            metric(
                                "search_on", "Tool search on", 39_700, 38_500, .tokens, "39.7k",
                                "38.5k", "▲ 1.2k", .worse),
                            metric(
                                "search_off", "Tool search off", 52_300, 51_900, .tokens,
                                "52.3k", "51.9k", "▲ 0.4k", .worse),
                            metric(
                                "nest_tools", "Nest tools", 6_200, 5_600, .tokens, "6.2k",
                                "5.6k", "▲ 0.6k", .worse, sub: "estimate"),
                            metric(
                                "nest_instructions", "Nest instructions", 3_100, 3_100, .tokens,
                                "3.1k", "3.1k", "0", .same, sub: "estimate"),
                        ]),
                    PerfSection(
                        id: "turns", title: "Turn speed and cache", ranAt: ran,
                        metrics: [
                            metric(
                                "first_reply", "First reply", 2_400, 2_400, .ms, "2.4 s", "2.4 s",
                                "0%", .same),
                            metric(
                                "typical", "Typical turn", 38_000, 40_000, .ms, "38 s", "40 s",
                                "▼ 5%", .better),
                            metric(
                                "cache_hit", "Cache hit rate", 91, 97, .percent, "91%", "97%",
                                "▼ 6%", .worse),
                        ]),
                    PerfSection(
                        id: "load", title: "Load speed", ranAt: ran,
                        note: "Times on the daemon; parsing on the device is not included.",
                        metrics: [
                            metric(
                                "open_app", "Open the app", 420, 480, .ms, "0.42 s", "0.48 s",
                                "▼ 12%", .better),
                            metric(
                                "biggest_chat", "Biggest chat", 1_800, 2_400, .ms, "1.8 s",
                                "2.4 s", "▼ 25%", .better, sub: "2.1 MB"),
                            metric(
                                "reconnect", "Reconnect", 300, 300, .ms, "0.30 s", "0.30 s", "0%",
                                .same),
                            metric(
                                "slow_network", "Slow phone network", 6_200, 5_960, .ms, "6.2 s",
                                "6.0 s", "▲ 4%", .worse),
                        ]),
                    PerfSection(
                        id: "waiting", title: "Waiting on you", ranAt: ran,
                        error: "The notification recorder has nothing since the daemon started.",
                        metrics: [
                            metric(
                                "answer_wait", "Typical wait for your answer", 240_000, 300_000,
                                .ms, "4 min", "5 min", "▼ 1 min", .better)
                        ]),
                    PerfSection(
                        id: "activity", title: "Activity, last 14 days", ranAt: ran,
                        metrics: [
                            metric(
                                "turns_per_day", "Turns per day", 212, 180, .count, "212", "180",
                                "▲ 18%", .same),
                            metric(
                                "tokens_per_day", "Tokens per day", 4_100_000, 3_980_000,
                                .tokens, "4.1M", "4.0M", "▲ 3%", .same),
                        ],
                        series: PerfSeries(
                            label: "Turns per day",
                            points: [40, 55, 48, 62, 30, 22, 70, 66, 58, 80, 74, 45, 88, 96]
                                .enumerated().map { index, value in
                                    PerfPoint(day: "2026-10-\(20 + index)", value: value)
                                })),
                    PerfSection(
                        id: "mac", title: "Mac app", advanced: true, runner: .mac,
                        metrics: [
                            metric("layout_ms", "Lay out the biggest chat", nil, nil, .ms, "-"),
                            metric("scroll_ms", "Scroll it through", nil, nil, .ms, "-"),
                        ]),
                    PerfSection(
                        id: "daemon", title: "Daemon", advanced: true, ranAt: ran,
                        metrics: [
                            metric(
                                "startup", "Startup", 1_900, 2_100, .ms, "1.9 s", "2.1 s", "▼ 10%",
                                .better)
                        ]),
                ],
                changes: [
                    PerfChange(text: "Context +1.2k: new MCP server linear", tone: .worse),
                    PerfChange(text: "Cache hit rate down 6% on Codex chats", tone: .worse),
                    PerfChange(
                        text: "Biggest chat opens 0.6 s faster since Nest 0.2", tone: .better),
                ],
                runs: 4)
        }

        private static func metric(
            _ id: String, _ label: String, _ value: Double?, _ previous: Double?, _ unit: PerfUnit,
            _ text: String, _ previousText: String? = nil, _ change: String? = nil,
            _ tone: PerfTone = .same, sub: String? = nil, parts: [PerfPart]? = nil
        ) -> PerfMetric {
            PerfMetric(
                id: id, label: label, sub: sub, value: value, unit: unit, text: text,
                previous: previous, previousText: previousText,
                change: change.map {
                    PerfChangeMark(
                        text: $0,
                        direction: $0.hasPrefix("▲") ? "up" : $0.hasPrefix("▼") ? "down" : "same",
                        tone: tone)
                },
                parts: parts)
        }
    }
#endif
