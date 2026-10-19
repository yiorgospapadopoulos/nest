// The source rendered in its place and cleaned; without marked it stays as it is.
var source = document.getElementById("nest-md");
var html = markdown(source.textContent);
if (html === null) {
  document.documentElement.classList.add("nest-fallback");
} else {
  var doc = element("article", "prose");
  doc.id = "nest-doc";
  doc.appendChild(clean(html, MARKDOWN));
  source.replaceWith(doc);
  markReady();
  // Diagrams drawn empty while the frame was not shown are drawn again once it is.
  var drawing = false;
  var redraw = function () {
    if (drawing || !undrawn(doc).length) return;
    drawing = true;
    drawDiagrams(doc).then(function () {
      drawing = false;
    });
  };
  redraw();
  onResize(document.documentElement, redraw);
}
