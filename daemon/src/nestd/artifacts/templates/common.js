// Small helpers every template's script uses.
// The page is rendered: its source and the loading ring go (loading.css), and a fallback
// shown while the libraries were slow gives way to the page.
function markReady() {
  document.documentElement.classList.remove("nest-fallback");
  document.documentElement.classList.add("nest-ready");
}
function each(list, fn) {
  Array.prototype.forEach.call(list, fn);
}
function element(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function escapeHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function readData(id) {
  try {
    var data = JSON.parse(document.getElementById(id).textContent);
    return Array.isArray(data) ? data : [];
  } catch (error) {
    return [];
  }
}
// Agent HTML (rendered Markdown, a design screen, a component) as nodes that cannot run
// anything. It is parsed in an inert template, so nothing loads or runs before it is
// cleaned, then cleaned by allow-lists: an element not allowed is removed with its contents
// when it can embed, load or run something (DROPPED), else replaced by its contents (MathML,
// unknown tags). Attributes not allowed go, event handlers always. A link keeps only an
// http, https or mailto address or an in-page #anchor, an image only a data: image.
function words(text) {
  var set = Object.create(null);
  each(text.split(/\s+/), function (word) {
    if (word) set[word] = true;
  });
  return set;
}
// The HTML and SVG namespaces, as the parser gives them.
var HTML_NS = document.documentElement.namespaceURI;
var SVG_NS = (function () {
  var template = document.createElement("template");
  template.innerHTML = "<svg></svg>";
  return template.content.firstChild.namespaceURI;
})();
var DROPPED = words(
  "script noscript template iframe frame frameset object embed applet param base meta portal " +
    "title xmp noembed noframes plaintext audio video source track picture canvas dialog " +
    "foreignobject use image animate set animatemotion animatetransform discard handler"
);
var SVG_ELEMENTS = words(
  "svg g path rect circle ellipse line polyline polygon text tspan textpath defs lineargradient " +
    "radialgradient stop clippath mask pattern marker symbol desc"
);
var SVG_ATTRIBUTES = words(
  "viewbox width height fill fill-rule clip-rule fill-opacity stroke stroke-width " +
    "stroke-opacity stroke-linecap stroke-linejoin stroke-dasharray stroke-dashoffset opacity " +
    "d x y x1 y1 x2 y2 cx cy r rx ry fx fy points transform offset stop-color stop-opacity " +
    "gradientunits gradienttransform spreadmethod patternunits patterncontentunits clip-path " +
    "clippathunits mask maskunits markerwidth markerheight refx refy orient marker-start " +
    "marker-mid marker-end font-size font-family font-weight font-style text-anchor " +
    "dominant-baseline letter-spacing dx dy preserveaspectratio xmlns id class role"
);
var TEXT_ELEMENTS =
  "a abbr article aside b bdi bdo blockquote br caption cite code col colgroup dd del details " +
  "dfn div dl dt em figcaption figure footer h1 h2 h3 h4 h5 h6 header hr i img input ins kbd " +
  "li main mark nav ol p pre q rp rt ruby s samp section small span strong sub summary sup " +
  "table tbody td tfoot th thead time tr u ul var wbr";
var TEXT_ATTRIBUTES =
  "id class title lang dir align alt src href width height colspan rowspan scope headers " +
  "start reversed type value checked disabled open datetime span role";
// Markdown: text, tables, images and links; no styles (a style element could restyle the
// page around it), only checkboxes as inputs (GFM task lists), no ids of the page's own.
var MARKDOWN = {
  elements: words(TEXT_ELEMENTS),
  attributes: words(TEXT_ATTRIBUTES),
  dropped: words("style link"),
  markdown: true,
};
// Screens and components (in their own shadow roots): also forms, styles and Google Fonts.
var SCREEN = {
  elements: words(
    TEXT_ELEMENTS +
      " button form label select option optgroup textarea fieldset legend progress meter" +
      " output address style link"
  ),
  attributes: words(
    TEXT_ATTRIBUTES +
      " style rel name placeholder for rows cols min max step maxlength minlength multiple" +
      " selected readonly required size tabindex hidden label pattern autocomplete inputmode"
  ),
  dropped: words(""),
  markdown: false,
};
function bare(value) {
  return String(value).replace(/[\u0000- \u007f-\u009f]+/g, "");
}
function safeLink(value, httpsOnly) {
  var address = bare(value);
  if (!httpsOnly && address.charAt(0) === "#") return true;
  var scheme = httpsOnly ? /^https:/i : /^(https?|mailto):/i;
  if (!scheme.test(address)) return false;
  try {
    return scheme.test(new URL(address).protocol);
  } catch (error) {
    return false;
  }
}
function keepAttribute(node, name, value, policy) {
  if (name.indexOf("on") === 0) return false;
  var svg = node.namespaceURI === SVG_NS;
  var allowed =
    (svg ? SVG_ATTRIBUTES[name] || (name === "style" && !policy.markdown) : policy.attributes[name]) ||
    /^aria-[a-z]+$/.test(name) ||
    (!policy.markdown && /^data-[a-z0-9-]+$/.test(name));
  if (!allowed) return false;
  if (name === "href") return safeLink(value, node.localName === "link");
  if (name === "src") return /^data:image\//i.test(bare(value));
  if (name === "id" && policy.markdown) return !/^nest-/i.test(bare(value));
  return true;
}
function verdict(node, policy) {
  var name = node.localName.toLowerCase();
  var html = node.namespaceURI === HTML_NS;
  if (DROPPED[name] || (html && policy.dropped[name])) return "drop";
  var allowed = html ? policy.elements[name] : node.namespaceURI === SVG_NS && SVG_ELEMENTS[name];
  if (!allowed) return "unwrap";
  if (name === "input" && policy.markdown && (node.getAttribute("type") || "").toLowerCase() !== "checkbox") {
    return "drop";
  }
  if (name === "link") {
    var stylesheet = /^\s*stylesheet\s*$/i.test(node.getAttribute("rel") || "");
    if (!stylesheet || !safeLink(node.getAttribute("href") || "", true)) return "drop";
  }
  return "keep";
}
function scrub(parent, policy) {
  var child = parent.firstChild;
  while (child) {
    var next = child.nextSibling;
    if (child.nodeType === 1) {
      var judged = verdict(child, policy);
      if (judged === "drop") {
        child.remove();
      } else {
        scrub(child, policy);
        if (judged === "unwrap") {
          while (child.firstChild) parent.insertBefore(child.firstChild, child);
          child.remove();
        } else {
          each(Array.prototype.slice.call(child.attributes), function (attribute) {
            var name = attribute.name.toLowerCase();
            if (!keepAttribute(child, name, attribute.value, policy)) {
              child.removeAttribute(attribute.name);
            }
          });
        }
      }
    } else if (child.nodeType !== 3) {
      child.remove();
    }
    child = next;
  }
}
function clean(html, policy) {
  var template = document.createElement("template");
  template.innerHTML = String(html);
  scrub(template.content, policy || MARKDOWN);
  return template.content;
}
