// Markdown to HTML with the pinned marked (GFM), Mermaid blocks as diagrams in the page's
// theme, other code highlighted when highlight.js knows the language. Without marked the
// callers keep the source as text. marked 12 passes the code and info string; later
// versions pass one token, read too.
var renderer = null;
var diagramsReady = false;
function dark() {
  return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
}
function codeBlock(code, info) {
  if (code && typeof code === "object") {
    info = code.lang;
    code = code.text;
  }
  code = String(code === undefined ? "" : code);
  var lang = String(info || "").trim().split(/\s+/)[0].toLowerCase();
  if (lang === "mermaid" && window.mermaid) {
    return '<pre class="mermaid">' + escapeHtml(code) + "</pre>";
  }
  if (window.hljs && lang && hljs.getLanguage(lang)) {
    var html = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
    return '<pre><code class="hljs">' + html + "</code></pre>";
  }
  return "<pre><code>" + escapeHtml(code) + "</code></pre>";
}
function markdown(text) {
  if (!window.marked || typeof marked.parse !== "function") return null;
  try {
    if (!renderer) {
      renderer = new marked.Renderer();
      renderer.code = codeBlock;
    }
    return String(marked.parse(text, { gfm: true, renderer: renderer }));
  } catch (error) {
    return null;
  }
}
// Mermaid measures labels and boxes on screen. In a frame the app has not shown yet (hidden,
// display: none, a hidden pane) everything measures zero, and Mermaid then draws an empty
// diagram, 16 by 16 with its padding, without an error. A frame can even measure text while
// its scripts start and stop before Mermaid draws. So diagrams are drawn once text measures,
// one that still comes out empty is drawn again at once (twice at most), and the templates
// draw empty ones again whenever the frame's size changes (a frame being shown), up to
// MAX_DRAWS times each.
var MAX_DRAWS = 6;
function isRendered() {
  var probe = element("span", "", "M");
  probe.style.cssText = "position: absolute; visibility: hidden;";
  document.body.appendChild(probe);
  var width = probe.getBoundingClientRect().width;
  probe.remove();
  return width > 0;
}
function whenRendered(callback) {
  if (isRendered()) return callback();
  var next =
    window.requestAnimationFrame ||
    function (fn) {
      setTimeout(fn, 100);
    };
  next(function () {
    whenRendered(callback);
  });
}
function isEmptyDiagram(node) {
  var svg = node.querySelector("svg");
  var box = String((svg && svg.getAttribute("viewBox")) || "").trim().split(/[\s,]+/);
  return !svg || (box.length === 4 && Number(box[2]) <= 16 && Number(box[3]) <= 16);
}
// Diagrams not drawn yet, or drawn empty and not given up on.
function undrawn(root) {
  if (!window.mermaid) return [];
  return Array.prototype.filter.call(root.querySelectorAll("pre.mermaid"), function (node) {
    var draws = Number(node.getAttribute("data-draws") || 0);
    return draws < MAX_DRAWS && (!node.hasAttribute("data-processed") || isEmptyDiagram(node));
  });
}
function runDiagrams(nodes) {
  try {
    if (!diagramsReady) {
      mermaid.initialize({
        startOnLoad: false,
        theme: "base",
        themeVariables: DIAGRAMS[dark() ? 1 : 0],
        securityLevel: "strict",
      });
      diagramsReady = true;
    }
    return Promise.resolve(mermaid.run({ nodes: nodes })).catch(function () {});
  } catch (error) {
    return Promise.resolve();
  }
}
function drawNodes(nodes, attempt) {
  each(nodes, function (node) {
    if (!node.hasAttribute("data-source")) node.setAttribute("data-source", node.textContent);
    node.setAttribute("data-draws", String(Number(node.getAttribute("data-draws") || 0) + 1));
    node.removeAttribute("data-processed");
    node.textContent = node.getAttribute("data-source");
  });
  return new Promise(function (resolve) {
    whenRendered(resolve);
  })
    .then(function () {
      return runDiagrams(nodes);
    })
    .then(function () {
      var empty = nodes.filter(function (node) {
        return isEmptyDiagram(node) && Number(node.getAttribute("data-draws")) < MAX_DRAWS;
      });
      if (empty.length && attempt < 2) return drawNodes(empty, attempt + 1);
    });
}
function drawDiagrams(root) {
  var nodes = undrawn(root);
  return nodes.length ? drawNodes(nodes, 0) : Promise.resolve();
}
// Calls back when the frame's size changes, including when a frame loaded hidden is shown
// (which gets no resize event).
function onResize(target, callback) {
  window.addEventListener("resize", callback);
  if (window.ResizeObserver) new ResizeObserver(callback).observe(target);
}
