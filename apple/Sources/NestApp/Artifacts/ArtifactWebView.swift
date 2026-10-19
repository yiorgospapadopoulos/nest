import AppKit
import NestKit
import SwiftUI
import WebKit

/// An artifact's page, which is untrusted agent output, in a web view that can go nowhere
/// (B79) and load only pinned libraries and fonts (B82): no stored data, a rule list that
/// blocks every other load, the content security policy in the page, only the first
/// navigation (the page itself) and in-page anchors, no new windows and no file access.
/// Its one way out is the `nest` message handler (B88), which takes only what
/// `ArtifactBridge` allows from the main frame; links go through the reader's "Open link?"
/// prompt. The page is never loaded before the rule list is installed. It takes Nest's
/// light or dark appearance, so `prefers-color-scheme` inside matches the app's theme.
/// Magnification stays off, so a pinch or a trackpad pan reaches the page (a design's
/// canvas zooms and pans itself). What the page stores goes to the daemon, and changes made
/// elsewhere come back into it as host events; `<input type=file>` asks with an open panel.
struct ArtifactWebView: NSViewRepresentable {
    let page: String
    let artifactID: String
    /// `ArtifactSandbox.rules()`, read before the view is made.
    let rules: WKContentRuleList
    /// The reader's prompt, which outlives this page.
    let prompt: ArtifactLinkPrompt
    /// A document's save (B88), nil for other kinds.
    let save: ArtifactBridgeSession.Save?
    let store: ArtifactsStore
    /// Export PDF's and Save file's handle on this page.
    let handle: ArtifactPageHandle

    func makeCoordinator() -> SandboxNavigation {
        let store = store
        let id = artifactID
        let handle = handle
        return SandboxNavigation(
            session: ArtifactBridgeSession(
                prompt: prompt, save: save,
                storage: { try await store.writeStorage(id, $0) },
                saveFile: { await handle.saveFile(name: $0, data: $1) },
                usage: { try await store.pageUsage() },
                ask: { try await store.ask(id, prompt: $0, system: $1) }
            ) { NSWorkspace.shared.open($0) })
    }

    func makeNSView(context: Context) -> PaneContentView {
        let container = PaneContentView()
        container.layer?.cornerRadius = 0
        let configuration = Self.configuration(rules)
        // The controller keeps its handlers, so it holds the coordinator only weakly.
        configuration.userContentController.addScriptMessageHandler(
            WeakBridgeHandler(context.coordinator), contentWorld: .page,
            name: ArtifactBridge.handlerName)
        configuration.userContentController.addUserScript(
            WKUserScript(
                source: ArtifactOpenPanel.watchScript, injectionTime: .atDocumentStart,
                forMainFrameOnly: true, in: Self.hostWorld))
        let view = NestWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        view.appearance = Self.appearance(context.environment.colorScheme)
        view.allowsMagnification = false
        container.show(view)
        context.coordinator.webView = view
        handle.webView = view
        let coordinator = context.coordinator
        let token = store.observeStorage(artifactID) { [weak coordinator] change in
            coordinator?.deliver(change)
        }
        let usageToken = store.observeUsage { [weak coordinator] usage in
            coordinator?.deliver(usage: usage)
        }
        coordinator.stopObserving = { [store] in
            store.stopObserving(token)
            store.stopObservingUsage(usageToken)
        }
        view.loadHTMLString(ArtifactHTML.sandboxed(page), baseURL: nil)
        return container
    }

    func updateNSView(_ container: PaneContentView, context: Context) {
        context.coordinator.webView?.appearance = Self.appearance(context.environment.colorScheme)
    }

    static func dismantleNSView(_ container: PaneContentView, coordinator: SandboxNavigation) {
        coordinator.stopObserving?()
        coordinator.stopObserving = nil
        coordinator.webView?.configuration.userContentController.removeScriptMessageHandler(
            forName: ArtifactBridge.handlerName, contentWorld: .page)
    }

    /// Nest's own scripts in the page, apart from the page's.
    static let hostWorld = WKContentWorld.world(name: ArtifactOpenPanel.world)

    /// The scheme SwiftUI resolved from Nest's theme, so the page follows Light, Dark or
    /// Auto as set in Nest and not only the system's.
    private static func appearance(_ scheme: ColorScheme) -> NSAppearance? {
        NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize, nsView: PaneContentView, context: Context
    ) -> CGSize? {
        PaneContentView.fill(proposal)
    }

    private static func configuration(_ rules: WKContentRuleList) -> WKWebViewConfiguration {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController.add(rules)
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        return configuration
    }
}

/// Lets the first navigation through, the page's own load, then only link clicks to an
/// anchor in the page. Any other link click (one the shim did not catch, such as a
/// middle click) is cancelled and asked about like `openLink`; `location` changes, form
/// posts, frames and refreshes are cancelled. New windows are never made. It answers the
/// page's bridge messages from its main frame.
final class SandboxNavigation: NSObject, WKNavigationDelegate, WKUIDelegate {
    private var loaded = false
    private let session: ArtifactBridgeSession
    weak var webView: WKWebView?
    /// Ends the storage observation `ArtifactWebView` started.
    var stopObserving: (() -> Void)?

    init(session: ArtifactBridgeSession) {
        self.session = session
    }

    func webView(
        _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        let mainFrame = navigationAction.targetFrame?.isMainFrame == true
        guard loaded else {
            loaded = mainFrame
            decisionHandler(mainFrame ? .allow : .cancel)
            return
        }
        let target = navigationAction.request.url
        if navigationAction.navigationType == .linkActivated {
            if mainFrame, ArtifactBridge.isAnchor(target, in: webView.url) {
                decisionHandler(.allow)
                return
            }
            if let target {
                Task { await session.follow(target) }
            }
        }
        decisionHandler(.cancel)
    }

    /// A storage change made elsewhere, handed to this page's shim in its main frame.
    func deliver(_ change: ArtifactStorageChange) {
        send(session.hostEvents(for: change))
    }

    /// Fresh usage, for a page that read its usage.
    func deliver(usage: ArtifactBridge.Value) {
        send(session.usageEvents(for: usage))
    }

    private func send(_ events: [ArtifactBridge.Value]) {
        guard let webView else { return }
        for event in events {
            if let script = ArtifactBridge.hostScript(event) {
                webView.evaluateJavaScript(script, in: nil, in: .page)
            }
        }
    }

    /// `<input type=file>`: an open panel on the window, files only, several when the
    /// input allows it. The page reads what is picked; nothing is uploaded.
    func webView(
        _ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping @MainActor ([URL]?) -> Void
    ) {
        guard let window = webView.window else {
            completionHandler(nil)
            return
        }
        let multiple = parameters.allowsMultipleSelection
        webView.evaluateJavaScript(
            ArtifactOpenPanel.script, in: nil, in: ArtifactWebView.hostWorld
        ) { result in
            let accept = (try? result.get()) as? String
            let panel = NSOpenPanel()
            panel.canChooseFiles = true
            panel.canChooseDirectories = false
            panel.allowsMultipleSelection = multiple
            if let types = ArtifactOpenPanel.types(accept: accept) {
                panel.allowedContentTypes = types
            }
            panel.beginSheetModal(for: window) { response in
                completionHandler(response == .OK ? panel.urls : nil)
            }
        }
    }

    func webView(
        _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        nil
    }

    /// Always answers, so the page's promise settles: with the reply object, or nil for a
    /// message that is ignored. Errors go in the reply, never the error string.
    func receive(
        _ message: WKScriptMessage, replyHandler: @escaping @MainActor (Any?, String?) -> Void
    ) {
        guard message.frameInfo.isMainFrame, let webView, message.webView === webView else {
            replyHandler(nil, nil)
            return
        }
        let body = message.body
        Task {
            replyHandler(await session.receive(body)?.body, nil)
        }
    }
}

/// The `nest` handler the content controller keeps, pointing at the coordinator weakly so
/// the web view's configuration does not keep it alive.
final class WeakBridgeHandler: NSObject, WKScriptMessageHandlerWithReply {
    private weak var target: SandboxNavigation?

    init(_ target: SandboxNavigation) {
        self.target = target
    }

    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
        replyHandler: @escaping @MainActor (Any?, String?) -> Void
    ) {
        guard let target else {
            replyHandler(nil, nil)
            return
        }
        target.receive(message, replyHandler: replyHandler)
    }
}

/// The reader's handle on its open page (B88). Export PDF for slides and documents: the
/// user picks where, then the page's own print operation writes the PDF on the paper
/// `ArtifactPrint` gives, as a sheet on the window. The template's print CSS lays the pages
/// out: one slide per landscape page, a document without its contents column or edit
/// controls. Save file: a page's `nest.saveFile`, a save panel as a sheet with the page's
/// suggested name.
@MainActor
final class ArtifactPageHandle: NSObject {
    weak var webView: WKWebView?
    private var finished: [ObjectIdentifier: (Bool) -> Void] = [:]
    /// Tells the user a file the page offered was saved or could not be.
    var reportSave: ((Result<URL, any Error>) -> Void)?

    /// False when the user cancels or the file cannot be written.
    func saveFile(name: String, data: Data) async -> Bool {
        guard let window = webView?.window else { return false }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = name
        guard await panel.beginSheetModal(for: window) == .OK, let url = panel.url else {
            return false
        }
        do {
            try data.write(to: url, options: .atomic)
            reportSave?(.success(url))
            return true
        } catch {
            reportSave?(.failure(error))
            return false
        }
    }

    func exportPDF(
        name: String, layout: ArtifactPrint, done: @escaping (_ saved: Bool, URL) -> Void
    ) {
        guard let window = webView?.window else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = name
        panel.allowedContentTypes = [.pdf]
        panel.beginSheetModal(for: window) { response in
            guard response == .OK, let url = panel.url else { return }
            // The print sheet waits until the save sheet has gone.
            Task { @MainActor in self.print(to: url, layout: layout) { done($0, url) } }
        }
    }

    private func print(to url: URL, layout: ArtifactPrint, done: @escaping (Bool) -> Void) {
        guard let webView, let window = webView.window else { return }
        let info = NSPrintInfo()
        info.orientation = layout.landscape ? .landscape : .portrait
        info.paperSize = NSSize(width: layout.width, height: layout.height)
        info.topMargin = layout.margin
        info.bottomMargin = layout.margin
        info.leftMargin = layout.margin
        info.rightMargin = layout.margin
        info.horizontalPagination = .fit
        info.verticalPagination = .automatic
        info.jobDisposition = .save
        info.dictionary()[NSPrintInfo.AttributeKey.jobSavingURL.rawValue] = url
        let operation = webView.printOperation(with: info)
        operation.showsPrintPanel = false
        operation.showsProgressPanel = true
        // A web view's print view starts with no size and would print blank pages.
        operation.view?.frame = webView.bounds
        finished[ObjectIdentifier(operation)] = done
        operation.runModal(
            for: window, delegate: self,
            didRun: #selector(printOperationDidRun(_:success:contextInfo:)), contextInfo: nil)
    }

    @objc private func printOperationDidRun(
        _ operation: NSPrintOperation, success: Bool, contextInfo: UnsafeMutableRawPointer?
    ) {
        finished.removeValue(forKey: ObjectIdentifier(operation))?(success)
    }
}

/// `ArtifactRules`, compiled once.
@MainActor
enum ArtifactSandbox {
    private static var compiling: Task<WKContentRuleList, any Error>?

    static func rules() async throws -> WKContentRuleList {
        if let compiling {
            return try await compiling.value
        }
        let task = Task { @MainActor in
            guard
                let list = try await WKContentRuleListStore.default().compileContentRuleList(
                    forIdentifier: ArtifactRules.identifier,
                    encodedContentRuleList: ArtifactRules.json)
            else { throw CocoaError(.featureUnsupported) }
            return list
        }
        compiling = task
        do {
            return try await task.value
        } catch {
            compiling = nil
            throw error
        }
    }
}
