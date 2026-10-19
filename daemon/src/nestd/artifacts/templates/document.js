// The document: sections split at `##` headings (outside code fences), rendered with their
// contents, and edited one at a time. Joining the sections with newlines gives back the
// source exactly, so a save rebuilds the whole Markdown from them.
var root = document.getElementById("nest-doc");
var holder = document.getElementById("nest-sections");
var sideToc = document.getElementById("nest-toc-side");
var topToc = document.getElementById("nest-toc-top");
var version = Number(root.getAttribute("data-version"));
var sections = splitSections(document.getElementById("nest-md").textContent);
var editing = null;
var CONFLICT = "This document changed; reload to edit the latest version";

function splitSections(text) {
  var parts = [[]];
  var fence = null;
  each(text.split("\n"), function (line) {
    var bare = line.replace(/\r$/, "");
    var mark = /^ {0,3}(`{3,}|~{3,})/.exec(bare);
    if (fence) {
      var closes =
        mark &&
        mark[1].charAt(0) === fence.charAt(0) &&
        mark[1].length >= fence.length &&
        /^ {0,3}(`+|~+)[ \t]*$/.test(bare);
      if (closes) fence = null;
    } else if (mark) {
      fence = mark[1];
    } else if (/^ {0,3}##(?:[ \t]|$)/.test(bare) && parts[parts.length - 1].length) {
      parts.push([]);
    }
    parts[parts.length - 1].push(line);
  });
  return parts.map(function (lines) {
    return lines.join("\n");
  });
}

// The whole Markdown with one section replaced; a blank line stays before the next heading.
function rebuild(index, text) {
  var next = sections.slice();
  if (index < next.length - 1 && text.slice(-1) !== "\n") text += "\n";
  next[index] = text;
  return next.join("\n");
}

function headingOf(text) {
  var found = /^ {0,3}##[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*\r?$/m.exec(text.split("\n")[0]);
  return found ? found[1] : "";
}

function canEdit() {
  return !!window.nest && typeof window.nest.saveDocument === "function";
}

function slug(text) {
  var base = String(text)
    .toLowerCase()
    .trim()
    .replace(/[^\p{L}\p{N}\s_-]+/gu, "")
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return base || "section";
}

function unique(base, used, node) {
  var id = base;
  for (var n = 2; ; n += 1) {
    var found = document.getElementById(id);
    if (!used[id] && (!found || found === node)) break;
    id = base + "-" + n;
  }
  used[id] = true;
  return id;
}

// Ids for the headings (a slug of their text, unique), and the contents' entries.
function nameHeadings(rendered) {
  var used = Object.create(null);
  var entries = [];
  if (rendered) {
    each(holder.querySelectorAll("h1, h2, h3, h4, h5, h6"), function (heading) {
      heading.id = unique(slug(heading.textContent), used, heading);
      if (heading.tagName === "H2" || heading.tagName === "H3") {
        var level = heading.tagName === "H2" ? 2 : 3;
        entries.push({ level: level, text: heading.textContent, id: heading.id });
      }
    });
    return entries;
  }
  each(holder.querySelectorAll(".nest-section"), function (section) {
    var text = headingOf(sections[Number(section.getAttribute("data-index"))]);
    if (!text) return;
    section.id = unique(slug(text), used, section);
    entries.push({ level: 2, text: text, id: section.id });
  });
  return entries;
}

function list(entries) {
  var items = element("ol", "toc");
  each(entries, function (entry) {
    var item = element("li", "toc-" + entry.level);
    var link = element("a", "", entry.text);
    link.setAttribute("href", "#" + entry.id);
    item.appendChild(link);
    items.appendChild(item);
  });
  return items;
}

function contents(entries) {
  var shown = entries.length >= 2;
  var topNav = topToc.querySelector("nav");
  root.classList.toggle("has-toc", shown);
  sideToc.hidden = !shown;
  topToc.hidden = !shown;
  sideToc.textContent = "";
  topNav.textContent = "";
  if (!shown) return;
  sideToc.appendChild(element("p", "toc-heading", "Contents"));
  sideToc.appendChild(list(entries));
  topNav.appendChild(list(entries));
}

function render() {
  var rendered = true;
  holder.textContent = "";
  each(sections, function (text, index) {
    if (!text.trim()) return;
    var section = element("section", "nest-section");
    section.setAttribute("data-index", String(index));
    if (canEdit()) {
      var edit = element("button", "nest-edit", "Edit");
      var heading = headingOf(text);
      edit.type = "button";
      edit.setAttribute("aria-label", heading ? "Edit section " + heading : "Edit the opening");
      edit.addEventListener("click", function () {
        startEdit(index);
      });
      section.appendChild(edit);
    }
    var body = element("div", "nest-section-body");
    var html = markdown(text);
    if (html === null) {
      rendered = false;
      body.appendChild(element("pre", "raw", text));
    } else {
      body.appendChild(clean(html, MARKDOWN));
    }
    section.appendChild(body);
    holder.appendChild(section);
  });
  contents(nameHeadings(rendered));
  document.body.classList.add("ready");
  markReady();
  redraw();
}

// Diagrams drawn empty while the frame was not shown are drawn again once it is.
var drawing = false;
function redraw() {
  if (drawing || !undrawn(holder).length) return;
  drawing = true;
  drawDiagrams(holder).then(function () {
    drawing = false;
  });
}
onResize(document.documentElement, redraw);

function setEditButtons(disabled) {
  each(holder.querySelectorAll(".nest-edit"), function (button) {
    button.disabled = disabled;
  });
}

function grow(area) {
  area.style.height = "auto";
  area.style.height = Math.max(160, area.scrollHeight + 2) + "px";
}

function startEdit(index) {
  if (editing || !canEdit()) return;
  var section = holder.querySelector('[data-index="' + index + '"]');
  var body = section.querySelector(".nest-section-body");
  var editor = element("div", "nest-editor");
  var area = element("textarea");
  var actions = element("div", "nest-editor-actions");
  var save = element("button", "button primary", "Save");
  var cancel = element("button", "button", "Cancel");
  var status = element("p", "nest-editor-status");
  area.value = sections[index];
  area.setAttribute("aria-label", "Markdown of this section");
  save.type = "button";
  cancel.type = "button";
  status.setAttribute("role", "status");
  actions.appendChild(save);
  actions.appendChild(cancel);
  actions.appendChild(status);
  editor.appendChild(area);
  editor.appendChild(actions);
  body.hidden = true;
  section.classList.add("is-editing");
  section.appendChild(editor);
  editing = {
    index: index,
    section: section,
    body: body,
    editor: editor,
    area: area,
    save: save,
    cancel: cancel,
    status: status,
  };
  setEditButtons(true);
  area.addEventListener("input", function () {
    grow(area);
  });
  area.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submit();
    }
  });
  save.addEventListener("click", submit);
  cancel.addEventListener("click", stopEdit);
  grow(area);
  area.focus();
}

function stopEdit() {
  if (!editing || editing.busy) return;
  editing.editor.remove();
  editing.body.hidden = false;
  editing.section.classList.remove("is-editing");
  editing = null;
  setEditButtons(false);
}

function submit() {
  if (!editing || editing.busy || editing.stale) return;
  var current = editing;
  var content = rebuild(current.index, current.area.value);
  if (content === sections.join("\n")) return stopEdit();
  current.busy = true;
  current.save.disabled = true;
  current.cancel.disabled = true;
  current.status.className = "nest-editor-status";
  current.status.textContent = "Saving";
  window.nest.saveDocument({ content: content, base_version: version }).then(
    function (result) {
      if (result && typeof result.version === "number") version = result.version;
      sections = splitSections(content);
      editing = null;
      render();
    },
    function (error) {
      current.busy = false;
      current.cancel.disabled = false;
      current.status.className = "nest-editor-status is-error";
      if (error && error.code === "conflict") {
        current.stale = true;
        current.status.textContent = CONFLICT;
      } else {
        current.save.disabled = false;
        current.status.textContent = (error && error.message) || "Could not save";
      }
    }
  );
}

// A link in the narrow contents closes them, then scrolls again (closing moves the page).
topToc.addEventListener("click", function (event) {
  var link = event.target && event.target.closest ? event.target.closest("a[href]") : null;
  if (!link) return;
  topToc.open = false;
  var target = document.getElementById(link.getAttribute("href").slice(1));
  if (target) target.scrollIntoView();
});

// The side contents mark the section being read.
var marking = false;
function markActive() {
  marking = false;
  var links = sideToc.querySelectorAll("a");
  var active = null;
  each(links, function (link) {
    var target = document.getElementById(link.getAttribute("href").slice(1));
    if (target && target.getBoundingClientRect().top < 80) active = link;
  });
  each(links, function (link) {
    link.classList.toggle("active", link === active);
  });
}
window.addEventListener(
  "scroll",
  function () {
    if (marking) return;
    marking = true;
    window.requestAnimationFrame(markActive);
  },
  { passive: true }
);

render();
