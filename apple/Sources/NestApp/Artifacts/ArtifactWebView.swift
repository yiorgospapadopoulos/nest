import AppKit
import NestKit
import SwiftUI
import WebKit

/// An HTML artifact, which is untrusted agent output, in a web view that can load
/// nothing and go nowhere (B79): no stored data, a rule list that blocks every load, the
/// content security policy in the page, only the first navigation (the page itself), no
/// new windows, no script message handlers and no file access. The page is never loaded
/// before the rule list is installed.
struct ArtifactWebView: NSViewRepresentable {
    let html: String
    /// `ArtifactSandbox.rules()`, read before the view is made.
    let rules: WKContentRuleList

    func makeCoordinator() -> SandboxNavigation {
        SandboxNavigation()
    }

    func makeNSView(context: Context) -> PaneContentView {
        let container = PaneContentView()
        container.layer?.cornerRadius = 0
        let view = NestWebView(frame: .zero, configuration: Self.configuration(rules))
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        container.show(view)
        view.loadHTMLString(ArtifactHTML.sandboxed(html), baseURL: nil)
        return container
    }

    func updateNSView(_ container: PaneContentView, context: Context) {}

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

/// Lets the first navigation through, the page's own load, and cancels every later one:
/// link clicks, `location` changes, form posts, frames and refreshes. New windows are
/// never made.
final class SandboxNavigation: NSObject, WKNavigationDelegate, WKUIDelegate {
    private var loaded = false

    func webView(
        _ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        guard !loaded, navigationAction.targetFrame?.isMainFrame == true else {
            decisionHandler(.cancel)
            return
        }
        loaded = true
        decisionHandler(.allow)
    }

    func webView(
        _ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        nil
    }
}

/// The rule list that blocks every load, compiled once.
@MainActor
enum ArtifactSandbox {
    static let blockEverything =
        #"[{"trigger": {"url-filter": ".*"}, "action": {"type": "block"}}]"#
    private static var compiling: Task<WKContentRuleList, any Error>?

    static func rules() async throws -> WKContentRuleList {
        if let compiling {
            return try await compiling.value
        }
        let task = Task { @MainActor in
            guard
                let list = try await WKContentRuleListStore.default().compileContentRuleList(
                    forIdentifier: "nest-artifact-block-everything",
                    encodedContentRuleList: blockEverything)
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
