import Foundation
import Testing

@testable import NestKit

/// Local models (B106): the daemon's shapes, its routes, the `local_server_down` refusal and
/// the event that local models changed.
@Suite struct LocalModelDecodingTests {
    static let modelJSON = """
        {"id": "lm_1", "server_id": "srv1", "model": "qwen/qwen3-coder-30b",
         "name": "qwen3-coder-30b", "address": "localhost:1234", "app": "LM Studio",
         "context": 65536, "tools": "good", "weak_reason": null, "vision": false,
         "thinking": true, "running": true, "has_key": false}
        """

    /// A model too big for this Mac's memory says so; an older daemon sends nothing.
    @Test func decodesTheMemoryWarning() {
        let warning = "Needs about 12 GB of this Mac's 24 GB: other work may slow down."
        let model = Fixture.decode(
            LocalModel.self,
            json: Self.modelJSON.replacingOccurrences(
                of: #""has_key": false}"#,
                with: #""has_key": false, "memory_warning": "\#(warning)"}"#))
        #expect(model.memoryWarning == warning)
        #expect(Fixture.decode(LocalModel.self, json: Self.modelJSON).memoryWarning == nil)
        let found = Fixture.decode(
            FoundModel.self,
            json: """
                {"address": "a", "app": null, "model": "m", "name": "m", "context": null,
                 "tools": "good", "weak_reason": null, "vision": false, "thinking": false,
                 "added": false, "memory_warning": "\(warning)"}
                """)
        #expect(found.memoryWarning == warning)
        let older = Fixture.decode(
            FoundModel.self,
            json: """
                {"address": "a", "app": null, "model": "m", "name": "m", "context": null,
                 "tools": "good", "weak_reason": null, "vision": false, "thinking": false,
                 "added": false, "memory_warning": null}
                """)
        #expect(older.memoryWarning == nil)
    }

    @Test func decodesAnAddedModel() {
        let model = Fixture.decode(LocalModel.self, json: Self.modelJSON)
        #expect(model.id == "lm_1")
        #expect(model.serverID == "srv1")
        #expect(model.model == "qwen/qwen3-coder-30b")
        #expect(model.name == "qwen3-coder-30b")
        #expect(model.address == "localhost:1234")
        #expect(model.app == "LM Studio")
        #expect(model.context == 65536)
        #expect(model.tools == .good)
        #expect(model.weakReason == nil)
        #expect(!model.vision)
        #expect(model.thinking)
        #expect(model.running)
        #expect(!model.hasKey)
        #expect(model.value == "local:lm_1")
        #expect(model.startApp == .lmstudio)
        #expect(!model.isWeak)
    }

    @Test func toolUseReadsEveryWordAndUnknownOnes() {
        let words = ["good", "weak", "none", "unknown", "brilliant"].map {
            Fixture.decode(LocalToolUse.self, json: "\"\($0)\"")
        }
        #expect(words == [.good, .weak, .noTools, .unknown, .unknown])
        #expect(
            LocalModel(id: "a", serverID: "s", model: "m", name: "m", address: "x", tools: .weak)
                .isWeak)
        #expect(
            LocalModel(id: "a", serverID: "s", model: "m", name: "m", address: "x", tools: .noTools)
                .isWeak)
        #expect(
            !LocalModel(
                id: "a", serverID: "s", model: "m", name: "m", address: "x", tools: .unknown
            )
            .isWeak)
    }

    @Test func appsAreKnownByTheirLabels() {
        #expect(LocalApp(label: "LM Studio") == .lmstudio)
        #expect(LocalApp(label: "Ollama") == .ollama)
        #expect(LocalApp(label: "llama.cpp") == nil)
        #expect(LocalApp(label: nil) == nil)
        #expect(LocalApp.lmstudio.title == "LM Studio")
        #expect(LocalApp.ollama.title == "Ollama")
    }

    @Test func aModelValueIsLocalByItsPrefix() {
        #expect(LocalModel.isLocal("local:lm_1"))
        #expect(!LocalModel.isLocal("opus"))
        #expect(!LocalModel.isLocal(nil))
    }

    @Test func decodesTheListWithItsEngineAndLocalOnly() {
        let list = Fixture.decode(
            LocalModelList.self,
            json: #"{"models": [\#(Self.modelJSON)], "engine": "codex", "local_only": true}"#)
        #expect(list.models.map(\.id) == ["lm_1"])
        #expect(list.engine == "codex")
        #expect(list.localOnly)
        #expect(LocalModelList(models: []).engine == "claude")
    }

    @Test func decodesWhatFindOnThisMacFound() {
        let find = Fixture.decode(
            LocalFind.self,
            json: """
                {"running": [{"address": "localhost:11434", "app": "Ollama", "model": "llama3.2:3b",
                  "name": "llama3.2:3b", "context": 4096, "tools": "weak",
                  "weak_reason": "Context of 4k is too small for an agent: set Ollama to 64k",
                  "vision": false, "thinking": false, "added": true}],
                 "downloaded": [{"name": "devstral-small-2", "source": "Ollama models folder",
                  "path": "/Users/x/.ollama/models/manifests/devstral", "hint": "start Ollama to use it",
                  "start": "ollama"},
                  {"name": "Qwen3.8-27B (MLX)", "source": "Hugging Face cache", "path": "/hf/q",
                   "hint": "open it in an app that serves MLX models", "start": null}]}
                """)
        let found = find.running[0]
        #expect(found.id == "localhost:11434/llama3.2:3b")
        #expect(found.app == "Ollama")
        #expect(found.context == 4096)
        #expect(found.tools == .weak)
        #expect(found.weakReason?.hasPrefix("Context of 4k") == true)
        #expect(found.added)
        #expect(find.downloaded.map(\.start) == [.ollama, nil])
        #expect(find.downloaded[0].id == "/Users/x/.ollama/models/manifests/devstral")
    }

    @Test func decodesACheckAndWhichEnginesItServes() {
        let check = Fixture.decode(
            LocalCheck.self,
            json: """
                {"ok": true, "error": null, "server": {"address": "localhost:8080", "app": null,
                 "messages": false, "responses": false, "chat": true},
                 "models": [{"address": "localhost:8080", "app": null, "model": "q", "name": "Q",
                 "context": null, "tools": "unknown", "weak_reason": null, "vision": false,
                 "thinking": false, "added": false}]}
                """)
        #expect(check.ok)
        #expect(check.error == nil)
        #expect(check.server?.worksWithClaude == true)
        #expect(check.server?.worksWithCodex == true)
        #expect(check.models.map(\.name) == ["Q"])
        let failed = Fixture.decode(
            LocalCheck.self,
            json: #"{"ok": false, "error": "no_tools", "server": null, "models": []}"#)
        #expect(failed.error == .noTools)
        let messagesOnly = LocalServerInfo(
            address: "a", app: nil, messages: true, responses: false, chat: false)
        #expect(messagesOnly.worksWithClaude)
        #expect(!messagesOnly.worksWithCodex)
        let responsesOnly = LocalServerInfo(
            address: "a", app: nil, messages: false, responses: true, chat: false)
        #expect(!responsesOnly.worksWithClaude)
        #expect(responsesOnly.worksWithCodex)
    }

    @Test func decodesUsageAndSetup() {
        let usage = Fixture.decode(
            LocalUsage.self,
            json:
                #"{"today_tokens": 48600, "models": [{"id": "lm_1", "input_tokens": 48000, "output_tokens": 600}]}"#
        )
        #expect(usage.todayTokens == 48600)
        #expect(
            usage.models == [LocalModelUsage(id: "lm_1", inputTokens: 48000, outputTokens: 600)])
        let setup = Fixture.decode(
            SetupState.self, json: #"{"first_run": true, "local_only": false}"#)
        #expect(setup == SetupState(firstRun: true, localOnly: false))
    }

    /// The key goes as null when none was typed, and models only when adding.
    @Test func requestsSendTheKeyAsNull() {
        #expect(
            Fixture.json(LocalServerRequest(address: "localhost:8080", key: nil, models: nil))
                == #"{"address":"localhost:8080","key":null}"#)
        #expect(
            Fixture.json(LocalServerRequest(address: "a", key: "k", models: ["m"]))
                == #"{"address":"a","key":"k","models":["m"]}"#)
    }

    @Test func localModelsChangedIsItsOwnEvent() {
        let event = Fixture.event(EventType.localModelsChanged, "{}", session: nil)
        #expect(event.body == .localModelsChanged)
        #expect(EventType.localModelsChanged == "local_models.changed")
    }
}

/// The local routes, as `APIClient` sends them.
@Suite struct LocalRouteTests {
    static let modelsJSON =
        #"{"models": [\#(LocalModelDecodingTests.modelJSON)], "engine": "claude", "local_only": false}"#

    static let routes: [RouteCase] = [
        RouteCase("GET", "/api/local/models", response: modelsJSON) {
            let list = try await $0.localModels()
            #expect(list.models.count == 1)
        },
        RouteCase("GET", "/api/local/find", response: #"{"running": [], "downloaded": []}"#) {
            let find = try await $0.findLocalModels()
            #expect(find.running.isEmpty)
        },
        RouteCase(
            "POST", "/api/local/check", body: #"{"address":"localhost:8080","key":null}"#,
            response: #"{"ok": false, "error": "unreachable", "server": null, "models": []}"#
        ) {
            let check = try await $0.checkLocalServer(address: "localhost:8080", key: nil)
            #expect(check.error == .unreachable)
        },
        RouteCase(
            "POST", "/api/local/models",
            body: #"{"address":"localhost:1234","key":"k","models":["a","b"]}"#,
            response: modelsJSON
        ) {
            let added = try await $0.addLocalModels(
                address: "localhost:1234", key: "k", models: ["a", "b"])
            #expect(added.map(\.id) == ["lm_1"])
        },
        RouteCase("DELETE", "/api/local/models/lm_1", response: "") {
            try await $0.removeLocalModel("lm_1")
        },
        RouteCase("PUT", "/api/local/engine", body: #"{"engine":"codex"}"#, response: "") {
            try await $0.setLocalEngine("codex")
        },
        RouteCase("POST", "/api/local/start", body: #"{"app":"ollama"}"#, response: "") {
            try await $0.startLocalServer(.ollama)
        },
        RouteCase(
            "GET", "/api/local/usage", response: #"{"today_tokens": 12, "models": []}"#
        ) {
            let usage = try await $0.localUsage()
            #expect(usage.todayTokens == 12)
        },
        RouteCase("GET", "/api/setup", response: #"{"first_run": true, "local_only": false}"#) {
            let setup = try await $0.setup()
            #expect(setup.firstRun)
        },
        RouteCase("POST", "/api/setup/local-only", response: "") {
            try await $0.useLocalOnly()
        },
        RouteCase("POST", "/api/setup/done", response: "") {
            try await $0.finishSetup()
        },
    ]

    let transport = FakeTransport()

    @Test(arguments: Self.routes)
    func sendsTheRouteAndReadsItsResponse(route: RouteCase) async throws {
        transport.reply(200, route.response)
        try await route.call(APIClient(token: "tok", transport: transport))
        let request = transport.last
        #expect(request.httpMethod == route.method)
        #expect(request.target == route.target)
        #expect(request.bodyText == route.body)
    }

    /// A send to a chat whose server is down is refused with what to start.
    @Test func aDownServerIsItsOwnError() async {
        transport.reply(
            409,
            #"{"detail": "LM Studio is not running", "code": "local_server_down", "app": "LM Studio", "address": "localhost:1234", "start": "lmstudio"}"#
        )
        let error = await #expect(throws: APIError.self) {
            _ = try await APIClient(token: "t", transport: transport).sendMessage(
                "s1", text: "hi", attachmentIDs: [])
        }
        let down = LocalServerDown(app: "LM Studio", address: "localhost:1234", start: .lmstudio)
        #expect(error == .localServerDown("LM Studio is not running", down))
        #expect(error?.message == "LM Studio is not running")
        #expect(error?.serverDown == down)
        #expect(error?.isConflict == false)
        #expect(APIError.conflict("x").serverDown == nil)
    }

    /// Without words or a known app, the refusal still reads.
    @Test func aDownServerWithoutWordsSaysSo() async {
        transport.reply(409, #"{"code": "local_server_down", "start": "nonsense"}"#)
        let error = await #expect(throws: APIError.self) {
            _ = try await APIClient(token: "t", transport: transport).localModels()
        }
        #expect(
            error
                == .localServerDown(
                    "The model's server is not running.",
                    LocalServerDown(app: nil, address: nil, start: nil)))
    }
}
