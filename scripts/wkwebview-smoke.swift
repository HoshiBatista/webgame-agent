// A one-off visual compatibility check, not a runtime or a gameplay verifier.
// The game never receives a native API bridge, file origin, or persistent storage.
import AppKit
import CryptoKit
import Foundation
import WebKit

func argument(_ flag: String, fallback: String? = nil) -> String {
    guard let index = CommandLine.arguments.firstIndex(of: flag), index + 1 < CommandLine.arguments.count else {
        if let fallback { return fallback }
        fputs("Missing argument \(flag)\n", stderr)
        exit(2)
    }
    return CommandLine.arguments[index + 1]
}

func hexHash(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

@MainActor
final class Smoke: NSObject, WKNavigationDelegate, WKUIDelegate {
    let input: URL
    let output: URL
    let width: Int
    let height: Int
    var window: NSWindow!
    var webView: WKWebView!
    var completed = false
    var scheduled = false
    var blockedNavigations = 0
    var htmlHash = ""

    init(input: URL, output: URL, width: Int, height: Int) {
        self.input = input
        self.output = output
        self.width = width
        self.height = height
        super.init()
    }

    func start() {
        do {
            let bytes = try Data(contentsOf: input)
            guard let html = String(data: bytes, encoding: .utf8) else {
                finish(error: "Export is not UTF-8")
                return
            }
            htmlHash = hexHash(bytes)
            try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
            let rulesURL = output.deletingLastPathComponent().appendingPathComponent("wk-rule-cache", isDirectory: true)
            try FileManager.default.createDirectory(at: rulesURL, withIntermediateDirectories: true)
            let store = WKContentRuleListStore(url: rulesURL)!
            let rules = """
            [
              {"trigger":{"url-filter":"^https?:"},"action":{"type":"block"}},
              {"trigger":{"url-filter":"^wss?:"},"action":{"type":"block"}},
              {"trigger":{"url-filter":"^ftp:"},"action":{"type":"block"}},
              {"trigger":{"url-filter":"^file:"},"action":{"type":"block"}}
            ]
            """
            store.compileContentRuleList(forIdentifier: "gameforge-visual-smoke-no-network", encodedContentRuleList: rules) { list, error in
                guard let list, error == nil else {
                    self.finish(error: "Content blocker could not be installed")
                    return
                }
                self.load(html: html, blocker: list)
            }
        } catch {
            finish(error: "Unable to prepare smoke check: \(error.localizedDescription)")
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) {
            if !self.completed { self.finish(error: "Visual smoke did not complete within 30 seconds") }
        }
    }

    func load(html: String, blocker: WKContentRuleList) {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.userContentController = WKUserContentController()
        configuration.userContentController.add(blocker)
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.mediaTypesRequiringUserActionForPlayback = .all
        // Intentionally no script-message handlers, custom URL schemes or native API objects.
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: width, height: height), configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        window = NSWindow(contentRect: webView.frame, styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "GameForge — isolated WKWebView visual smoke"
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)
        let escaped = html.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
        let wrapper = """
        <!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; worker-src 'none'; frame-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'">
        <style>html,body{width:100%;height:100%;margin:0;overflow:hidden;background:#fff}iframe{display:block;width:100%;height:100%;border:0}</style></head>
        <body><iframe id="game" sandbox="allow-scripts" referrerpolicy="no-referrer" srcdoc="\(escaped)"></iframe></body></html>
        """
        // No file URL or filesystem base URL is ever exposed to WebKit.
        webView.loadHTMLString(wrapper, baseURL: nil)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = navigationAction.request.url?.absoluteString ?? ""
        if url == "about:blank" || url == "about:srcdoc" || url.isEmpty {
            decisionHandler(.allow)
        } else {
            blockedNavigations += 1
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard !scheduled else { return }
        scheduled = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            // Introspection is on our wrapper only. It does not add a callable native bridge.
            webView.evaluateJavaScript("document.querySelector('#game').contentDocument === null") { value, error in
                guard error == nil, (value as? Bool) == true else {
                    self.finish(error: "Expected an opaque-origin sandbox frame")
                    return
                }
                let options = WKSnapshotConfiguration()
                options.rect = webView.bounds
                webView.takeSnapshot(with: options) { image, error in
                    guard error == nil, let image,
                          let tiff = image.tiffRepresentation,
                          let bitmap = NSBitmapImageRep(data: tiff),
                          let png = bitmap.representation(using: .png, properties: [:]) else {
                        self.finish(error: "WKWebView snapshot failed")
                        return
                    }
                    do {
                        try png.write(to: self.output.appendingPathExtension("png"), options: .atomic)
                        self.finish(pngHash: hexHash(png))
                    } catch {
                        self.finish(error: "Unable to write snapshot")
                    }
                }
            }
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        finish(error: "WebKit content process terminated")
    }

    func finish(error: String? = nil, pngHash: String? = nil) {
        guard !completed else { return }
        completed = true
        let report: [String: Any] = [
            "status": error == nil ? "visual_snapshot_created" : "failed",
            "error": error ?? NSNull(),
            "html_sha256": htmlHash,
            "snapshot_sha256": pngHash ?? NSNull(),
            "viewport": ["width": width, "height": height],
            "os": ProcessInfo.processInfo.operatingSystemVersionString,
            "webview": "macOS WKWebView",
            "opaque_sandbox": error == nil,
            "persistent_storage": false,
            "native_api_bridge": false,
            "network_policy": "CSP connect-src none + content rules block http/https/ws/wss/ftp/file + navigation allowlist about:blank/about:srcdoc; inline data/blob artwork allowed by CSP",
            "blocked_navigations": blockedNavigations,
            "scope": "visual smoke only; gameplay is verified separately in Chromium; not the contest host"
        ]
        if let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: output.appendingPathExtension("json"), options: .atomic)
            print(String(decoding: data, as: UTF8.self))
        }
        window?.orderOut(nil)
        if error != nil { exit(1) }
        NSApp.terminate(nil)
    }
}

MainActor.assumeIsolated {
    let application = NSApplication.shared
    application.setActivationPolicy(.accessory)
    let smoke = Smoke(input: URL(fileURLWithPath: argument("--html")), output: URL(fileURLWithPath: argument("--out")), width: Int(argument("--width", fallback: "390")) ?? 390, height: Int(argument("--height", fallback: "844")) ?? 844)
    smoke.start()
    application.run()
}
