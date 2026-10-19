// Agent HTML for a design screen or a component, shown in its own shadow root: style stays
// inside it, nothing in it runs (it is cleaned first) and nothing in it navigates (link
// clicks and form submits are stopped). `:root` and `html` in its CSS become `:host`, `body`
// the wrapper around it.
function hostify(css) {
  return String(css).replace(/(^|[{};])([^{};@]+)(?=\{)/g, function (all, edge, selector) {
    return (
      edge +
      selector
        .replace(/:root(?![\w-])/g, ":host")
        .replace(/(^|[\s,>+~(])html(?![\w-])/g, "$1:host")
        .replace(/(^|[\s,>+~(])body(?![\w-])/g, "$1.nest-body")
    );
  });
}

function sanitize(html) {
  var content = clean(html, SCREEN);
  each(content.querySelectorAll("style"), function (node) {
    node.textContent = hostify(node.textContent);
  });
  return content;
}

function stopNavigation(event) {
  var path = event.composedPath ? event.composedPath() : [event.target];
  for (var index = 0; index < path.length; index += 1) {
    var name = path[index] && path[index].localName;
    if (name === "a" || name === "area") return event.preventDefault();
  }
}

function mount(host, html, style) {
  try {
    var shadow = host.attachShadow({ mode: "open" });
    var base = document.createElement("style");
    var body = document.createElement("div");
    base.textContent = style;
    body.className = "nest-body";
    body.appendChild(sanitize(html));
    shadow.appendChild(base);
    shadow.appendChild(body);
    shadow.addEventListener("click", stopNavigation, true);
    shadow.addEventListener("submit", function (event) {
      event.preventDefault();
    }, true);
  } catch (error) {
    host.textContent = "This preview could not be shown.";
  }
}
