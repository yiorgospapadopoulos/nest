// The mockups: each screen in its frame's shadow root, fitted to its column, in the layout
// the data asks for (the viewer can switch); a click opens a screen fitted large; the canvas
// layout pans and zooms. A pinch arrives either as two touches or as gesture events, never
// both.
var SCREEN_STYLE =
  ":host { all: initial; display: block; overflow: hidden; color-scheme: light; background: #fff;" +
  " color: #000; font: 16px/1.5 -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial," +
  " sans-serif; }\n.nest-body { min-height: 100%; container-type: inline-size;" +
  " container-name: screen; }\n";
var MIN = 0.05;
var MAX = 4;
var PAD = 24;
var LAYOUTS = ["stack", "grid", "tabs", "canvas"];
var canvas = document.getElementById("nest-canvas");
var world = document.getElementById("nest-world");
var zoomLabel = document.getElementById("nest-zoom");
var viewer = document.getElementById("nest-viewer");
var screens = readData("nest-data");
var mockups = Array.prototype.slice.call(document.querySelectorAll(".mockup"));
var tabs = Array.prototype.slice.call(document.querySelectorAll('.tabs [role="tab"]'));
var layout = document.body.getAttribute("data-layout");
var selected = 0;
var view = { x: PAD, y: PAD, scale: 1 };
var moved = false;

function renderMarkdown(node) {
  var html = node && markdown(node.textContent);
  if (html === null || !node) return;
  var rendered = element("div", "prose");
  rendered.appendChild(clean(html, MARKDOWN));
  node.replaceWith(rendered);
}
renderMarkdown(document.getElementById("nest-notes"));
each(document.querySelectorAll(".mockup-desc pre"), renderMarkdown);

function mountScreen(host) {
  var html = screens[Number(host.getAttribute("data-screen"))];
  mount(host, typeof html === "string" ? html : "", SCREEN_STYLE);
}
each(document.querySelectorAll(".mockups [data-screen]"), mountScreen);

// A device fitted into its stage: never above its own size, and in a stack or tabs no
// taller than the window allows, so a screen is seen whole without scrolling.
function padding(node, side) {
  return parseFloat(window.getComputedStyle(node)["padding" + side]) || 0;
}
function fitDevice(stage, maxHeight) {
  var device = stage.querySelector(".device");
  var sizer = stage.querySelector(".sizer");
  var room = stage.getBoundingClientRect().width - padding(stage, "Left") - padding(stage, "Right");
  if (!device || !(room > 0)) return;
  var width = Number(device.getAttribute("data-width"));
  var height = Number(device.getAttribute("data-height"));
  var scale = Math.min(1, room / width, maxHeight > 0 ? maxHeight / height : 1);
  device.style.transform = "scale(" + scale + ")";
  sizer.style.width = width * scale + "px";
  sizer.style.height = height * scale + "px";
}
function tallest() {
  if (layout === "grid") return 0;
  var offset = layout === "tabs" ? 260 : 120;
  return Math.max(320, (window.innerHeight || 800) - offset);
}
function fitAll() {
  if (layout === "canvas") return fitCanvasDevices();
  each(document.querySelectorAll(".mockups .stage"), function (stage) {
    fitDevice(stage, tallest());
  });
}
function fitCanvasDevices() {
  each(document.querySelectorAll(".mockups .device"), function (device) {
    var sizer = device.parentNode;
    device.style.transform = "";
    sizer.style.width = device.getAttribute("data-width") + "px";
    sizer.style.height = device.getAttribute("data-height") + "px";
  });
}

// Layouts.
function setLayout(next) {
  layout = LAYOUTS.indexOf(next) >= 0 ? next : "stack";
  document.body.setAttribute("data-layout", layout);
  each(document.querySelectorAll("[data-layout]"), function (button) {
    if (button !== document.body) {
      button.setAttribute("aria-pressed", button.getAttribute("data-layout") === layout ? "true" : "false");
    }
  });
  if (layout === "tabs") select(selected, false);
  else each(mockups, function (mockup) {
    mockup.classList.remove("is-selected");
    mockup.removeAttribute("role");
  });
  if (layout === "canvas") {
    fitAll();
    fitCanvas();
  } else {
    world.style.transform = "";
    world.style.removeProperty("--nest-zoom");
    fitAll();
  }
}
document.querySelector(".layouts").addEventListener("click", function (event) {
  var button = event.target && event.target.closest ? event.target.closest("[data-layout]") : null;
  if (button) setLayout(button.getAttribute("data-layout"));
});

// Tabs: one mockup at a time; arrows, Home and End move between them.
function select(index, focus) {
  if (!mockups.length) return;
  selected = (index + mockups.length) % mockups.length;
  each(tabs, function (tab, at) {
    var on = at === selected;
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
    if (on && focus) tab.focus();
  });
  each(mockups, function (mockup, at) {
    mockup.classList.toggle("is-selected", at === selected);
    mockup.setAttribute("role", "tabpanel");
  });
  fitAll();
}
each(tabs, function (tab, at) {
  tab.addEventListener("click", function () {
    select(at, false);
  });
  tab.addEventListener("keydown", function (event) {
    var step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (Object.prototype.hasOwnProperty.call(step, event.key)) select(selected + step[event.key], true);
    else if (event.key === "Home") select(0, true);
    else if (event.key === "End") select(mockups.length - 1, true);
    else return;
    event.preventDefault();
  });
});

// The overlay: a mockup fitted large; arrows step, Escape or a click outside closes it.
var opener = null;
var showing = -1;
function show(index) {
  showing = (index + mockups.length) % mockups.length;
  var mockup = mockups[showing];
  var stage = viewer.querySelector(".viewer-stage");
  var device = mockup.querySelector(".device").cloneNode(true);
  var sizer = element("div", "sizer");
  device.style.transform = "";
  sizer.appendChild(device);
  stage.textContent = "";
  stage.appendChild(sizer);
  mountScreen(device.querySelector("[data-screen]"));
  viewer.querySelector(".viewer-badge").textContent = mockup.getAttribute("data-label");
  viewer.querySelector(".viewer-title").textContent = mockup.querySelector(".mockup-title").textContent;
  viewer.querySelector(".viewer-count").textContent = showing + 1 + " of " + mockups.length;
  fitViewer();
}
function fitViewer() {
  var stage = viewer.querySelector(".viewer-stage");
  var device = stage.querySelector(".device");
  if (!device) return;
  var box = stage.getBoundingClientRect();
  var width = Number(device.getAttribute("data-width"));
  var height = Number(device.getAttribute("data-height"));
  var roomWidth = box.width - padding(stage, "Left") - padding(stage, "Right");
  var roomHeight = box.height - padding(stage, "Top") - padding(stage, "Bottom");
  var scale = roomWidth > 0 && roomHeight > 0 ? Math.min(1, roomWidth / width, roomHeight / height) : 1;
  device.style.transform = "scale(" + scale + ")";
  device.parentNode.style.width = width * scale + "px";
  device.parentNode.style.height = height * scale + "px";
}
function openViewer(index, from) {
  opener = from || null;
  viewer.hidden = false;
  document.body.classList.add("is-viewing");
  show(index);
  viewer.querySelector(".viewer-close").focus();
}
function closeViewer() {
  if (viewer.hidden) return;
  viewer.hidden = true;
  showing = -1;
  document.body.classList.remove("is-viewing");
  viewer.querySelector(".viewer-stage").textContent = "";
  if (opener && opener.focus) opener.focus();
  opener = null;
}
each(document.querySelectorAll(".mockups .stage"), function (stage) {
  var index = Number(stage.closest(".mockup").getAttribute("data-index"));
  stage.addEventListener("click", function () {
    if (layout !== "canvas") openViewer(index, stage);
  });
  stage.addEventListener("keydown", function (event) {
    if (layout === "canvas" || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    openViewer(index, stage);
  });
});
viewer.addEventListener("click", function (event) {
  var target = event.target;
  if (target === viewer || target.classList.contains("viewer-stage")) return closeViewer();
  if (target.closest && target.closest(".viewer-close")) return closeViewer();
  var step = target.closest ? target.closest("[data-step]") : null;
  if (step) show(showing + Number(step.getAttribute("data-step")));
});

// The canvas: pan by drag, wheel or two-finger scroll; zoom by pinch, ctrl or cmd plus
// wheel, keys and the buttons. Only in the canvas layout.
function clamp(scale) {
  return Math.min(MAX, Math.max(MIN, scale));
}
function apply() {
  world.style.setProperty("--nest-zoom", String(view.scale));
  world.style.transform = "translate(" + view.x + "px, " + view.y + "px) scale(" + view.scale + ")";
  zoomLabel.textContent = Math.round(view.scale * 100) + "%";
}
function zoomAt(scale, x, y) {
  scale = clamp(scale);
  view.x = x - (x - view.x) * (scale / view.scale);
  view.y = y - (y - view.y) * (scale / view.scale);
  view.scale = scale;
  moved = true;
  apply();
}
function center() {
  return { x: canvas.clientWidth / 2, y: canvas.clientHeight / 2 };
}
// Fitted: the whole world in view, never above 100%. Labels keep their size on screen, so
// the world is measured again at the new scale.
function fitCanvas() {
  var scale = 1;
  var width = 0;
  var height = 0;
  for (var pass = 0; pass < 3; pass += 1) {
    world.style.setProperty("--nest-zoom", String(scale));
    width = world.offsetWidth;
    height = world.offsetHeight;
    if (!width || !height || !canvas.clientWidth || !canvas.clientHeight) break;
    if (pass < 2) {
      scale = clamp(
        Math.min((canvas.clientWidth - PAD * 2) / width, (canvas.clientHeight - PAD * 2) / height, 1)
      );
    }
  }
  view.scale = scale;
  view.x = width ? (canvas.clientWidth - width * scale) / 2 : PAD;
  view.y = height ? Math.max(PAD, (canvas.clientHeight - height * scale) / 2) : PAD;
  moved = false;
  apply();
}
function local(event) {
  var box = canvas.getBoundingClientRect();
  return { x: event.clientX - box.left, y: event.clientY - box.top };
}
var pointers = new Map();
var gesture = null;
function begin() {
  var points = Array.from(pointers.values());
  canvas.classList.toggle("is-panning", points.length > 0);
  if (points.length === 1) {
    gesture = { from: points[0], x: view.x, y: view.y };
  } else if (points.length >= 2) {
    var a = points[0];
    var b = points[1];
    gesture = {
      distance: Math.hypot(a.x - b.x, a.y - b.y) || 1,
      middle: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
      x: view.x,
      y: view.y,
      scale: view.scale,
    };
  } else {
    gesture = null;
  }
}
canvas.addEventListener("pointerdown", function (event) {
  if (layout !== "canvas" || (event.pointerType === "mouse" && event.button !== 0)) return;
  pointers.set(event.pointerId, local(event));
  try {
    canvas.setPointerCapture(event.pointerId);
  } catch (error) {}
  begin();
});
canvas.addEventListener("pointermove", function (event) {
  if (!pointers.has(event.pointerId) || !gesture) return;
  pointers.set(event.pointerId, local(event));
  var points = Array.from(pointers.values());
  if (gesture.from) {
    view.x = gesture.x + points[0].x - gesture.from.x;
    view.y = gesture.y + points[0].y - gesture.from.y;
  } else {
    var a = points[0];
    var b = points[1];
    var scale = clamp(gesture.scale * (Math.hypot(a.x - b.x, a.y - b.y) / gesture.distance));
    var middle = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    view.x = middle.x - (gesture.middle.x - gesture.x) * (scale / gesture.scale);
    view.y = middle.y - (gesture.middle.y - gesture.y) * (scale / gesture.scale);
    view.scale = scale;
  }
  moved = true;
  apply();
});
function release(event) {
  if (!pointers.delete(event.pointerId)) return;
  begin();
}
canvas.addEventListener("pointerup", release);
canvas.addEventListener("pointercancel", release);
var pinchFrom = null;
canvas.addEventListener(
  "wheel",
  function (event) {
    if (layout !== "canvas") return;
    var point = local(event);
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      if (pinchFrom !== null) return;
      var delta = Math.max(-50, Math.min(50, event.deltaY));
      zoomAt(view.scale * Math.exp(-delta * 0.01), point.x, point.y);
      return;
    }
    var unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1;
    view.x -= event.deltaX * unit;
    view.y -= event.deltaY * unit;
    moved = true;
    apply();
  },
  { passive: false }
);
// WebKit's gesture events: a trackpad pinch on the Mac, and on the iPhone alongside the
// touches, which then do the zooming.
canvas.addEventListener("gesturestart", function (event) {
  if (layout !== "canvas") return;
  event.preventDefault();
  pinchFrom = pointers.size ? null : view.scale;
});
canvas.addEventListener("gesturechange", function (event) {
  if (layout !== "canvas") return;
  event.preventDefault();
  if (pinchFrom === null || pointers.size) return;
  var point = local(event);
  zoomAt(pinchFrom * event.scale, point.x, point.y);
});
canvas.addEventListener("gestureend", function (event) {
  if (layout !== "canvas") return;
  event.preventDefault();
  pinchFrom = null;
});
document.querySelector(".zoom-tools").addEventListener("click", function (event) {
  var button = event.target && event.target.closest ? event.target.closest("[data-zoom]") : null;
  if (!button) return;
  var middle = center();
  var zoom = button.getAttribute("data-zoom");
  if (zoom === "fit") fitCanvas();
  else zoomAt(view.scale * (zoom === "in" ? 1.25 : 0.8), middle.x, middle.y);
});
document.addEventListener("keydown", function (event) {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
  if (!viewer.hidden) {
    if (event.key === "Escape") closeViewer();
    else if (event.key === "ArrowRight") show(showing + 1);
    else if (event.key === "ArrowLeft") show(showing - 1);
    else return;
    return event.preventDefault();
  }
  if (layout !== "canvas") return;
  var middle = center();
  if (event.key === "+" || event.key === "=") zoomAt(view.scale * 1.25, middle.x, middle.y);
  else if (event.key === "-" || event.key === "_") zoomAt(view.scale * 0.8, middle.x, middle.y);
  else if (event.key === "0") fitCanvas();
  else return;
  event.preventDefault();
});
onResize(document.documentElement, function () {
  fitAll();
  if (!viewer.hidden) fitViewer();
  if (layout === "canvas" && !moved) fitCanvas();
});
window.addEventListener("load", function () {
  if (layout === "canvas" && !moved) fitCanvas();
});
setLayout(layout);
markReady();
