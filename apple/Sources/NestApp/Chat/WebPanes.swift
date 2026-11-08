import AppKit
import NestKit
import Observation
import SwiftUI
import WebKit

/// The chat transcripts as web pages (D151): each pane's transcript is the web chat in its
/// own web view, and everything around it stays native. The page comes from the daemon, so
/// it has the daemon's version and origin on this Mac and on a remote one, and it asks the
/// app for the token (`WebPaneBridge`), which stays out of its address and of any script.
/// A page lives as long as its pane: going to another view or moving the pane keeps it, its
/// scroll place and its open rows; closing the pane frees it. A page that cannot show says
/// so in its pane and comes back when the daemon does (`PageFailure`).
@MainActor @Observable
final class WebPanes: NSObject {
    /// Pages kept while no view shows them, such as another project's; the oldest beyond
    /// this load again when next shown.
    private static let keptOffScreen = 6
    /// How long a page may take to say it is ready before it counts as not working.
    private static let startLimit = Duration.seconds(12)
    /// A page that ends sooner than this after the last end stops reloading by itself.
    private static let crashWindow = Duration.seconds(30)

    @ObservationIgnored private let model: AppModel
    @ObservationIgnored weak var shell: Shell?
    @ObservationIgnored private var pages: [WebPaneBridge.Target: WebPane] = [:]
    /// The views showing each page, newest last. SwiftUI may build a second one before it
    /// drops either, and a sheet can show a chat a pane shows too; the page goes to the
    /// newest, and back when that one leaves.
    @ObservationIgnored private var holders: [WebPaneBridge.Target: [PaneContentView]] = [:]
    @ObservationIgnored private var configuration: WKWebViewConfiguration?
    @ObservationIgnored private var rules: Task<Void, Never>?
    /// Pages that could not show, which their panes say.
    private var failed: Set<WebPaneBridge.Target> = []

    init(model: AppModel) {
        self.model = model
        super.init()
    }

    /// Whether this page can show: it did not fail, and there is a daemon to ask.
    func shows(_ target: WebPaneBridge.Target) -> Bool {
        model.pageConnection != nil && !failed.contains(target)
    }

    /// Tries the page again.
    func retry(_ target: WebPaneBridge.Target) {
        failed.remove(target)
    }

    /// The daemon is back: every page that could not show tries again.
    func retryAll() {
        failed = []
    }

    /// The target's page, loading it the first time.
    func page(for target: WebPaneBridge.Target, transient: Bool = false) -> WebPane {
        if let page = pages[target] {
            return page
        }
        let page = WebPane(target: target, transient: transient, configuration: shared())
        page.navigationDelegate = self
        page.uiDelegate = self
        page.setValue(false, forKey: "drawsBackground")
        page.allowsMagnification = false
        pages[target] = page
        Task { await load(page) }
        return page
    }

    /// Sends a command to the pane's page, whenever it gets there.
    func send(_ command: WebPaneBridge.Command, to target: WebPaneBridge.Target) {
        if shows(target) {
            page(for: target).send(command)
        }
    }

    /// Shows the page in `container`.
    func hold(
        _ target: WebPaneBridge.Target, in container: PaneContentView, transient: Bool
    ) -> WebPane {
        let page = page(for: target, transient: transient)
        holders[target, default: []].removeAll { $0 === container }
        holders[target, default: []].append(container)
        container.show(page)
        return page
    }

    /// `container` stopped showing the page: another view takes it, else it waits.
    func release(_ target: WebPaneBridge.Target, from container: PaneContentView) {
        holders[target]?.removeAll { $0 === container }
        if holders[target]?.isEmpty == true {
            holders[target] = nil
        }
        guard let page = pages[target] else { return }
        if let next = holders[target]?.last {
            next.show(page)
        } else {
            page.removeFromSuperview()
            left(page)
        }
    }

    /// Frees the pages of panes no project shows any more. A page a view still holds goes
    /// when the view does.
    func keep(_ panes: Set<String>) {
        for (target, page) in pages
        where !page.isTransient && holders[target] == nil && !panes.contains(target.chat) {
            close(target)
        }
        failed = failed.filter { panes.contains($0.chat) }
    }

    func close(_ target: WebPaneBridge.Target) {
        guard let page = pages.removeValue(forKey: target) else { return }
        page.stopLoading()
        page.removeFromSuperview()
        page.navigationDelegate = nil
        page.uiDelegate = nil
    }

    func closeAll() {
        Array(pages.keys).forEach(close)
        holders = [:]
    }

    /// No view shows `page`: a sheet's page and a closed pane's go, the others stay a while.
    private func left(_ page: WebPane) {
        if page.isTransient || shell?.openChats.contains(page.target.chat) != true {
            close(page.target)
            return
        }
        page.leftAt = .now
        let waiting = pages.values.filter { holders[$0.target] == nil }
            .sorted { $0.leftAt > $1.leftAt }
        for page in waiting.dropFirst(Self.keptOffScreen) {
            close(page.target)
        }
    }

    /// Everything the pages share: the rule list and the message handler. WebKit gives each
    /// page its own process all the same; the GPU and network processes are shared.
    private func shared() -> WKWebViewConfiguration {
        if let configuration {
            return configuration
        }
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        configuration.userContentController.addScriptMessageHandler(
            self, contentWorld: .page, name: WebPaneBridge.handlerName)
        self.configuration = configuration
        if let base = model.pageConnection?.baseURL {
            rules = Task { await install(rulesFor: base, in: configuration) }
        }
        return configuration
    }

    private func install(rulesFor base: URL, in configuration: WKWebViewConfiguration) async {
        let list = try? await WKContentRuleListStore.default().compileContentRuleList(
            forIdentifier: WebPaneBridge.rulesIdentifier(base: base),
            encodedContentRuleList: WebPaneBridge.contentRules(base: base))
        if let list {
            configuration.userContentController.add(list)
        }
    }

    /// Nothing loads before the rule list is in place.
    private func load(_ page: WebPane) async {
        await rules?.value
        guard pages[page.target] === page, let base = model.pageConnection?.baseURL else { return }
        guard let address = WebPaneBridge.address(base: base, target: page.target)
        else { return }
        page.load(URLRequest(url: address))
        await watchStart(of: page)
    }

    /// A page that never says it is ready counts as failed, so no pane stays blank.
    private func watchStart(of page: WebPane) async {
        try? await Task.sleep(for: Self.startLimit)
        if pages[page.target] === page, !page.isReady {
            fail(page)
        }
    }

    private func fail(_ page: WebPane) {
        guard pages[page.target] === page else { return }
        failed.insert(page.target)
        close(page.target)
    }

    private func run(_ message: WebPaneBridge.Message, from page: WebPane) {
        guard let shell else { return }
        let chat = page.target.chat
        // What leaves a work sheet leaves it for the chat behind.
        let leave = {
            if case .work = page.target {
                shell.close()
            }
        }
        switch message {
        case .daemon: break
        case .ready: page.becameReady()
        case .openLink(let url): NSWorkspace.shared.open(url)
        case .openFile(let path):
            let root =
                shell.sessions.session(chat)?.folder ?? shell.claudeChat(inPane: chat)?.cwd
            if let root {
                shell.openFile(path, root: root)
            }
        case .openChat(let id):
            leave()
            shell.openChat(id)
        case .openPixie(let id):
            leave()
            shell.revealPixie(id)
        case .copy(let text): shell.copyText(text)
        case .toast(let text, let failed): shell.show(text, kind: failed ? .failed : .info)
        case .teamWork(let team):
            let entry = shell.chatPixies.group(session: chat).first {
                $0.kind == .team && $0.teamID == team
            }
            let members =
                entry?.members.map(\.pixieID)
                ?? shell.pixies.pixies.filter { $0.teamID == team }.map(\.id)
            shell.openWork(.team(session: chat, teamID: team, members: members))
        case .pixieWork(let pixie): shell.openWork(.pixie(session: chat, pixieID: pixie))
        case .message(.edit, let event): shell.startEdit(chat, message: event)
        case .message(.rewind, let event): shell.startRewind(chat, message: event)
        case .message(.fork, let event): shell.fork(chat, message: event)
        case .artifact(let id, let version): shell.openArtifact(id, version: version, from: chat)
        case .terminal(let command): shell.runInTerminal(command: command, from: chat)
        case .image(let id): shell.show(.image(id))
        case .saveFile(let name, let data):
            let panel = NSSavePanel()
            panel.nameFieldStringValue = name
            guard panel.runModal() == .OK, let url = panel.url else { return }
            do {
                try data.write(to: url)
            } catch {
                shell.show(error, doing: "Could not save the file")
            }
        }
    }
}

extension WebPanes: WKScriptMessageHandlerWithReply {
    /// Only the daemon's own page in a pane is answered.
    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
        replyHandler: @escaping @MainActor @Sendable (Any?, String?) -> Void
    ) {
        let origin = message.frameInfo.securityOrigin
        guard let connection = model.pageConnection, message.frameInfo.isMainFrame,
            WebPaneBridge.isDaemon(
                scheme: origin.protocol, host: origin.host, port: origin.port,
                base: connection.baseURL),
            let page = message.webView as? WebPane, pages[page.target] === page,
            let parsed = WebPaneBridge.parse(message.body)
        else {
            replyHandler(nil, "refused")
            return
        }
        if parsed == .daemon {
            let base = connection.baseURL.absoluteString
            replyHandler(["base": base, "token": connection.token], nil)
        } else {
            replyHandler(nil, nil)
            run(parsed, from: page)
        }
    }
}

extension WebPanes: WKNavigationDelegate, WKUIDelegate {
    func webView(
        _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        guard let base = model.pageConnection?.baseURL else {
            decisionHandler(.cancel)
            return
        }
        let clicked = navigationAction.navigationType == .linkActivated
        switch WebPaneBridge.navigation(
            to: navigationAction.request.url, base: base, linkClick: clicked)
        {
        case .stay: decisionHandler(.allow)
        case .openOutside(let url):
            if clicked {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel)
        case .cancel: decisionHandler(.cancel)
        }
    }

    /// A daemon without the page answers with an error, which is no page to show.
    func webView(
        _ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
        decisionHandler: @escaping @MainActor (WKNavigationResponsePolicy) -> Void
    ) {
        let status = (navigationResponse.response as? HTTPURLResponse)?.statusCode ?? 200
        if status >= 400, let page = webView as? WebPane {
            fail(page)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }

    /// `target=_blank` links ask for a new window; they go to the browser instead.
    func webView(
        _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url.flatMap({ SafeLink.url($0.absoluteString) }) {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func webView(
        _ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
        withError error: any Error
    ) {
        if let page = webView as? WebPane {
            fail(page)
        }
    }

    func webView(
        _ webView: WKWebView, didFail navigation: WKNavigation!, withError error: any Error
    ) {
        if let page = webView as? WebPane {
            fail(page)
        }
    }

    /// WebKit ended the page's process, as it does under memory pressure: it loads again,
    /// and a page that keeps ending says so instead.
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        guard let page = webView as? WebPane else { return }
        let now = ContinuousClock.now
        defer { page.lastEnd = now }
        if let last = page.lastEnd, last.duration(to: now) < Self.crashWindow {
            fail(page)
        } else {
            page.restarted()
            Task { await watchStart(of: page) }
        }
    }
}

/// One page.
final class WebPane: WKWebView {
    let target: WebPaneBridge.Target
    /// A sheet's page, which goes when the sheet does.
    let isTransient: Bool
    var leftAt = Date.distantPast
    /// When its process last ended.
    var lastEnd: ContinuousClock.Instant?
    private(set) var isReady = false
    /// The latest script of each command kind, resent to a page that starts again.
    private var latest: [String: String] = [:]
    /// Those already delivered.
    private var delivered: [String: String] = [:]

    init(
        target: WebPaneBridge.Target, transient: Bool, configuration: WKWebViewConfiguration
    ) {
        self.target = target
        isTransient = transient
        super.init(frame: .zero, configuration: configuration)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) is not supported")
    }

    // Sidebar drags pass through to the pane's drop targets, as in a browser pane.
    override func registerForDraggedTypes(_ newTypes: [NSPasteboard.PasteboardType]) {}

    /// Reloading would throw the place away, and going back has nowhere to go.
    override func willOpenMenu(_ menu: NSMenu, with event: NSEvent) {
        super.willOpenMenu(menu, with: event)
        let gone = [
            "WKMenuItemIdentifierReload", "WKMenuItemIdentifierGoBack",
            "WKMenuItemIdentifierGoForward",
        ]
        for item in menu.items where gone.contains(item.identifier?.rawValue ?? "") {
            menu.removeItem(item)
        }
        if menu.items.allSatisfy(\.isSeparatorItem) {
            menu.removeAllItems()
        }
    }

    func send(_ command: WebPaneBridge.Command) {
        guard let script = WebPaneBridge.script(command), latest[command.kind] != script else {
            return
        }
        latest[command.kind] = script
        if isReady {
            deliver()
        }
        if case .focus = command {
            // Asked again later, the same message scrolls and glows again.
            latest[command.kind] = nil
        }
    }

    /// Whether the page's messages have drawn, for timing it.
    func showsMessages() async -> Bool {
        guard isReady else { return false }
        return await withCheckedContinuation { continuation in
            evaluateJavaScript("document.querySelector('.dc-item') !== null") { value, _ in
                continuation.resume(returning: value as? Bool ?? false)
            }
        }
    }

    func becameReady() {
        isReady = true
        deliver()
    }

    func restarted() {
        isReady = false
        delivered = [:]
        reload()
    }

    private func deliver() {
        for (kind, script) in latest where delivered[kind] != script {
            delivered[kind] = script
            evaluateJavaScript(script)
        }
    }
}

/// A chat's transcript: its web page, or the line saying it could not be loaded.
struct ChatTranscript: View {
    let chat: String
    /// In a sheet, whose page goes with it; a pane's page outlives the view.
    var transient = false
    @Environment(Shell.self) private var shell

    var body: some View {
        let title = shell.sessions.session(chat)?.title ?? shell.claudeChat(inPane: chat)?.title
        WebPage(
            target: .pane(chat), transient: transient, label: "this chat",
            name: title.map { "Transcript of \($0)" } ?? "Transcript"
        )
        .task(id: chat) {
            if !shell.isClaudeChatPane(chat) {
                try? await shell.activity.load(session: chat)
            }
        }
    }
}

/// A web page, or what stands in for one that cannot show.
struct WebPage: View {
    let target: WebPaneBridge.Target
    var transient = false
    /// What the failure line calls it.
    let label: String
    /// What VoiceOver calls the page; every page's own title is "Nest".
    let name: String
    @Environment(Shell.self) private var shell

    var body: some View {
        if shell.webPanes.shows(target) {
            WebPaneView(
                target: target, transient: transient, accent: shell.settings.accent.rawValue,
                bash: shell.bash.rows(chat: target.chat), name: name)
        } else {
            PageFailure(target: target, label: label)
        }
    }
}

/// A page that could not load: a plain line and Retry. It also tries again when the daemon
/// comes back.
private struct PageFailure: View {
    let target: WebPaneBridge.Target
    let label: String
    @Environment(Shell.self) private var shell

    var body: some View {
        VStack(spacing: 8) {
            Text("Could not load \(label)")
                .font(.ui(TypeSize.ui))
                .foregroundStyle(Palette.t2)
            Button("Retry") { shell.webPanes.retry(target) }
                .buttonStyle(.nest(.soft))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onChange(of: shell.app.connection == .connected) { _, connected in
            if connected {
                shell.webPanes.retryAll()
            }
        }
    }
}

private struct WebPaneView: NSViewRepresentable {
    let target: WebPaneBridge.Target
    let transient: Bool
    let accent: String
    let bash: [BashStore.Row]
    let name: String
    @Environment(Shell.self) private var shell

    final class Coordinator {
        var target: WebPaneBridge.Target?
        var panes: WebPanes?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> PaneContentView {
        PaneContentView()
    }

    func updateNSView(_ container: PaneContentView, context: Context) {
        let coordinator = context.coordinator
        let panes = shell.webPanes
        if coordinator.target != target, let old = coordinator.target {
            panes.release(old, from: container)
            coordinator.target = nil
        }
        let page: WebPane
        if coordinator.target == nil {
            page = panes.hold(target, in: container, transient: transient)
            coordinator.target = target
            coordinator.panes = panes
        } else {
            page = panes.page(for: target, transient: transient)
        }
        container.isHidden = context.environment.paneHidden
        if page.accessibilityLabel() != name {
            page.setAccessibilityLabel(name)
        }
        let dark = context.environment.colorScheme == .dark
        page.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        page.send(.dimmed(context.environment.paneDimmed))
        page.send(.appearance(dark: dark, accent: accent))
        page.send(.bash(bash))
    }

    static func dismantleNSView(_ container: PaneContentView, coordinator: Coordinator) {
        if let target = coordinator.target {
            coordinator.panes?.release(target, from: container)
        }
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, nsView: PaneContentView, context: Context
    ) -> CGSize? {
        PaneContentView.fill(proposal)
    }
}
