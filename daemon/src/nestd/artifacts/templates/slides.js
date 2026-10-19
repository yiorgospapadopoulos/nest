// The deck: slides split from the source, the stage scaled to the frame, and navigation.
// The current slide lives only in this script, never in the URL.
var WIDTH = 1280;
var HEIGHT = 720;
// The slide's padding, top and bottom, and the counter's line under the stage.
var PAD_Y = 64;
var CHROME = 20;
var deck = document.getElementById("nest-deck");
var stage = document.getElementById("nest-stage");
var count = document.getElementById("nest-count");
var progress = document.getElementById("nest-progress");
var slides = [];
var current = 0;

function splitSlides(text) {
  var parts = [[]];
  each(text.split("\n"), function (line) {
    if (line.replace(/\r$/, "") === "---") parts.push([]);
    else parts[parts.length - 1].push(line);
  });
  var found = parts
    .map(function (lines) {
      return lines.join("\n");
    })
    .filter(function (part) {
      return part.trim() !== "";
    });
  return found.length ? found : [""];
}

// A slide of one heading first and at most three short blocks is laid out as a title slide.
function isTitle(content) {
  var blocks = content.children;
  if (!blocks.length || blocks.length > 4 || blocks[0].tagName !== "H1") return false;
  for (var index = 1; index < blocks.length; index += 1) {
    if (!/^(H[1-6]|P)$/.test(blocks[index].tagName)) return false;
  }
  return true;
}

function build(texts) {
  each(texts, function (text, index) {
    var slide = element("section", "slide");
    slide.setAttribute("aria-roledescription", "slide");
    slide.setAttribute("aria-label", index + 1 + " of " + texts.length);
    var content = element("div", "slide-body");
    var html = markdown(text);
    if (html === null) {
      content.appendChild(element("pre", "slide-raw", text));
    } else {
      content.appendChild(clean(html, MARKDOWN));
      if (isTitle(content)) slide.classList.add("is-title");
    }
    slide.appendChild(content);
    stage.appendChild(slide);
    slides.push(slide);
    each(content.querySelectorAll("img"), function (image) {
      image.addEventListener("load", function () {
        fitSlide(slide);
      });
    });
  });
}

// Content taller than the slide is scaled down to fit, never scrolled. Scaling widens the
// content box to match, which shortens it, so the scale only ever shrinks.
function fitSlide(slide) {
  var content = slide.firstChild;
  var room = HEIGHT - PAD_Y * 2;
  var scale = 1;
  content.style.transform = "";
  content.style.width = "";
  slide.classList.remove("is-fitted");
  for (var pass = 0; pass < 4 && content.scrollHeight * scale > room; pass += 1) {
    scale = Math.max(0.2, Math.min(scale, room / content.scrollHeight) * (pass ? 0.97 : 1));
    content.style.transform = "scale(" + scale + ")";
    content.style.width = 100 / scale + "%";
    slide.classList.add("is-fitted");
  }
}

function fitAll() {
  each(slides, fitSlide);
}

function layout() {
  var outerWidth = deck.clientWidth || window.innerWidth || WIDTH;
  var outerHeight = deck.clientHeight || window.innerHeight || HEIGHT;
  var pad = Math.round(Math.min(24, outerWidth * 0.03, outerHeight * 0.03));
  var width = outerWidth - pad * 2;
  var height = outerHeight - pad * 2 - CHROME;
  var scale = Math.max(0.01, Math.min(width / WIDTH, height / HEIGHT));
  var left = (outerWidth - WIDTH * scale) / 2;
  var top = (outerHeight - CHROME - HEIGHT * scale) / 2;
  stage.style.transform = "translate(" + left + "px, " + top + "px) scale(" + scale + ")";
}

function show(index) {
  current = Math.max(0, Math.min(slides.length - 1, index));
  each(slides, function (slide, at) {
    var on = at === current;
    slide.classList.toggle("current", on);
    slide.setAttribute("aria-hidden", on ? "false" : "true");
    slide.inert = !on;
  });
  count.textContent = current + 1 + " / " + slides.length;
  progress.style.width = ((current + 1) / slides.length) * 100 + "%";
}

function go(index) {
  if (index !== current && index >= 0 && index < slides.length) show(index);
}

document.addEventListener("keydown", function (event) {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
  var target = event.target;
  if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) {
    return;
  }
  switch (event.key) {
    case "ArrowRight":
    case "ArrowDown":
    case "PageDown":
      go(current + 1);
      break;
    case " ":
      go(current + (event.shiftKey ? -1 : 1));
      break;
    case "ArrowLeft":
    case "ArrowUp":
    case "PageUp":
      go(current - 1);
      break;
    case "Home":
      go(0);
      break;
    case "End":
      go(slides.length - 1);
      break;
    default:
      return;
  }
  event.preventDefault();
});

// A horizontal swipe of one finger moves a slide; two fingers are a pinch, never a swipe.
var swipe = null;
var swiped = false;
var touches = 0;
deck.addEventListener("pointerdown", function (event) {
  swiped = false;
  if (event.pointerType === "mouse") return;
  touches += 1;
  swipe = touches === 1 ? { x: event.clientX, y: event.clientY } : null;
});
function lift() {
  touches = Math.max(0, touches - 1);
}
deck.addEventListener("pointercancel", function () {
  lift();
  swipe = null;
});
deck.addEventListener("pointerup", function (event) {
  if (event.pointerType === "mouse") return;
  lift();
  if (!swipe) return;
  var dx = event.clientX - swipe.x;
  var dy = event.clientY - swipe.y;
  swipe = null;
  if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy) * 1.2) return;
  swiped = true;
  go(current + (dx < 0 ? 1 : -1));
});
// A click or tap on the left third goes back, on the right third forward.
deck.addEventListener("click", function (event) {
  if (swiped) {
    swiped = false;
    return;
  }
  if (event.defaultPrevented) return;
  var target = event.target;
  if (target && target.closest && target.closest("a, button, input, textarea, select")) return;
  if (window.getSelection && String(window.getSelection())) return;
  var width = deck.clientWidth || window.innerWidth;
  var x = event.clientX - deck.getBoundingClientRect().left;
  if (x < width / 3) go(current - 1);
  else if (x > (width * 2) / 3) go(current + 1);
});

build(splitSlides(document.getElementById("nest-md").textContent));
document.body.classList.add("ready");
show(0);
// The stage is scaled and fitted once the frame has a size, and again whenever it changes.
// Diagrams are drawn first, on the unscaled stage, hidden: Mermaid measures its labels on
// screen, and a scaled stage would clip them. Any that came out empty (the frame was not
// shown yet) are drawn the same way when the frame's size changes.
var drawing = false;
function draw() {
  drawing = true;
  deck.style.opacity = "0";
  stage.style.transform = "";
  return drawDiagrams(stage).then(function () {
    drawing = false;
    deck.style.opacity = "";
    settle();
  });
}
function settle(resized) {
  if (drawing || !deck.getBoundingClientRect().width) return;
  if (resized === true && undrawn(stage).length) return draw();
  layout();
  fitAll();
  markReady();
}
onResize(deck, function () {
  settle(true);
});
if (undrawn(stage).length) draw();
else settle();
