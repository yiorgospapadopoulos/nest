"""The shim every artifact page gets (B88, D115): `window.nest`, the page's side of the bridge
to the app that shows it. A request is `{nest: 1, id, method, params}`; the reply is
`{nest: 1, id, ok: true, result}` or `{nest: 1, id, ok: false, error: {code, message}}`. On
the Mac it goes to the `nest` reply handler; on the iPhone to the parent frame, which answers
with a message. Link clicks and `window.open` become `openLink`, which the app confirms. The
shim scrolls to in-page anchors itself: an iPhone srcdoc frame resolves `#x` against the
app's own URL, so following the link would load the app in the frame. The other methods
(`saveDocument`, B88 stage 2) are plain calls with their params; the app decides where each
is allowed. As a guard against a save nobody asked for, the shim refuses `saveDocument`
unless the user clicked or pressed a key in the last 5 seconds; it is not a security
boundary (a page's script can post to the app itself). That boundary is that document and
slides pages run only Nest's template script, with the agent's Markdown cleaned. On the
iPhone the app can also send the event `{nest: 1, event: "print"}`, and the shim prints the
page with the browser's own `print`, kept before any page script could replace it.
"""

import json
import re
from collections.abc import Mapping

_SOURCE = """(function () {
  "use strict";
  var methods = __METHODS__;
  var userActions = __USER_ACTIONS__;
  var realPrint = window.print;
  var now = Date.now;
  var trusted = -Infinity;
  var pending = Object.create(null);
  var counter = 0;
  var suffix = Math.random().toString(36).slice(2, 10);
  var mac = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.nest;
  var init = readInit();
  function noop() {}
  // The page's initial data, read once and removed: what it stored, its files.
  function readInit() {
    var data = null;
    try {
      var node = document.getElementById("nest-init");
      if (node) {
        data = JSON.parse(node.textContent);
        node.parentNode.removeChild(node);
      }
    } catch (error) {}
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  }
  function failure(code, message) {
    var error = new Error(message || code);
    error.code = code;
    return error;
  }
  function settle(reply) {
    if (!reply || typeof reply !== "object" || reply.nest !== 1) return;
    var entry = typeof reply.id === "string" && pending[reply.id];
    if (!entry) return;
    delete pending[reply.id];
    clearTimeout(entry.timer);
    if (reply.ok === true) return entry.resolve(reply.result);
    var error = reply.error || {};
    var code = typeof error.code === "string" ? error.code : "unavailable";
    entry.reject(failure(code, typeof error.message === "string" ? error.message : ""));
  }
  function call(method, params) {
    return new Promise(function (resolve, reject) {
      counter += 1;
      var id = counter + "-" + suffix;
      var request = { nest: 1, id: id, method: method, params: params };
      function gone(message) {
        settle({ nest: 1, id: id, ok: false, error: { code: "unavailable", message: message } });
      }
      pending[id] = { resolve: resolve, reject: reject };
      pending[id].timer = setTimeout(function () { gone("Nest did not answer"); }, 120000);
      try {
        if (mac) {
          mac.postMessage(request).then(settle, function () { gone("Nest did not answer"); });
        } else if (window.parent !== window) {
          window.parent.postMessage(request, "*");
        } else {
          gone("Nest is not here");
        }
      } catch (error) {
        gone("Nest is not here");
      }
    });
  }
  function openLink(url) {
    return call("openLink", { url: url });
  }
  function quietly(url) {
    openLink(url).catch(function () {});
  }
  function jump(fragment) {
    var name = fragment;
    try {
      name = decodeURIComponent(fragment);
    } catch (error) {}
    var target = name ? document.getElementById(name) || document.getElementsByName(name)[0] : null;
    if (target) target.scrollIntoView();
    else if (!name || name.toLowerCase() === "top") window.scrollTo(0, 0);
  }
  function onClick(event) {
    try {
      if (event.defaultPrevented || !event.target || !event.target.closest) return;
      var link = event.target.closest("a[href]");
      if (!link) return;
      var raw = link.getAttribute("href") || "";
      var href = typeof link.href === "string" ? link.href : new URL(raw, document.baseURI).href;
      var here = location.href.split("#")[0];
      var mark = href.indexOf("#");
      event.preventDefault();
      if (raw.charAt(0) === "#") return jump(raw.slice(1));
      if (mark >= 0 && href.slice(0, mark) === here) return jump(href.slice(mark + 1));
      quietly(href);
    } catch (error) {
      event.preventDefault();
    }
  }
  // nest.storage: kept per artifact by the app, shared with the user's other devices. Reads
  // come from a cache filled at load; writes change the cache at once and go to the app
  // together, one call at most every 300 ms, in order.
  var CAPS = { key: 256, value: 256 * 1024, keys: 1000, total: 2 * 1024 * 1024 };
  var cache = Object.create(null);
  var sizes = Object.create(null);
  var total = 0;
  var count = 0;
  var listeners = [];
  var batch = null;
  var queue = Promise.resolve();
  function utf8(text) {
    var size = 0;
    for (var at = 0; at < text.length; at += 1) {
      var unit = text.charCodeAt(at);
      if (unit < 0x80) size += 1;
      else if (unit < 0x800) size += 2;
      else if (unit >= 0xd800 && unit < 0xdc00 && at + 1 < text.length) {
        size += 4;
        at += 1;
      } else size += 3;
    }
    return size;
  }
  function has(key) {
    return Object.prototype.hasOwnProperty.call(cache, key);
  }
  function put(key, value) {
    if (has(key)) total -= sizes[key];
    else count += 1;
    cache[key] = value;
    sizes[key] = utf8(key) + utf8(value);
    total += sizes[key];
  }
  function drop(key) {
    if (!has(key)) return;
    total -= sizes[key];
    count -= 1;
    delete cache[key];
    delete sizes[key];
  }
  function wipe() {
    cache = Object.create(null);
    sizes = Object.create(null);
    total = 0;
    count = 0;
  }
  var stored = init.storage && typeof init.storage === "object" ? init.storage : {};
  Object.keys(stored).forEach(function (key) {
    if (typeof stored[key] === "string") put(key, stored[key]);
  });
  function refusal(key, value) {
    if (typeof key !== "string" || key.length < 1 || key.length > CAPS.key) {
      return failure("bad_request", "A key is 1 to 256 characters");
    }
    if (typeof value !== "string") {
      return failure("bad_request", "A value is a string; store JSON.stringify(value)");
    }
    var size = utf8(key) + utf8(value);
    if (utf8(value) > CAPS.value) return failure("quota", "A value may be at most 256 KiB");
    if (!has(key) && count >= CAPS.keys) {
      return failure("quota", "Storage may hold at most 1,000 keys");
    }
    if (total - (has(key) ? sizes[key] : 0) + size > CAPS.total) {
      return failure("quota", "Storage may hold at most 2 MiB");
    }
    return null;
  }
  function settleAll(waiters, error) {
    waiters.forEach(function (waiter) {
      if (error) waiter.reject(error);
      else waiter.resolve();
    });
  }
  function flush() {
    var sending = batch;
    batch = null;
    if (!sending) return;
    var set = {};
    Object.keys(sending.set).forEach(function (key) {
      set[key] = sending.set[key];
    });
    var remove = Object.keys(sending.remove);
    queue = queue
      .then(function () {
        return call("storageWrite", { set: set, remove: remove });
      })
      .then(
        function () {
          settleAll(sending.waiters, null);
        },
        function (error) {
          settleAll(sending.waiters, error);
        }
      );
  }
  function write(change) {
    if (!batch) {
      batch = { set: Object.create(null), remove: Object.create(null), waiters: [] };
      setTimeout(flush, 300);
    }
    change(batch);
    var current = batch;
    return new Promise(function (resolve, reject) {
      current.waiters.push({ resolve: resolve, reject: reject });
    });
  }
  function storageSet(key, value) {
    var problem = refusal(key, value);
    if (problem) return Promise.reject(problem);
    put(key, value);
    return write(function (next) {
      next.set[key] = value;
      delete next.remove[key];
    });
  }
  function storageRemove(key) {
    key = String(key);
    drop(key);
    return write(function (next) {
      delete next.set[key];
      next.remove[key] = true;
    });
  }
  function storageClear() {
    var dropped = batch;
    batch = null;
    wipe();
    var cleared = queue.then(function () {
      return call("storageClear", {});
    });
    queue = cleared.then(noop, noop);
    return cleared.then(
      function () {
        if (dropped) settleAll(dropped.waiters, null);
      },
      function (error) {
        if (dropped) settleAll(dropped.waiters, error);
        throw error;
      }
    );
  }
  function notify(key, value) {
    listeners.slice().forEach(function (listener) {
      try {
        listener({ key: key, value: value });
      } catch (error) {}
    });
    try {
      window.dispatchEvent(new StorageEvent("storage", { key: key, newValue: value }));
    } catch (error) {}
  }
  // nest.usage and nest.onUsage: the user's Claude usage as Nest's Usage page shows it. The
  // first listener asks for it once, so the app knows to send this page its updates.
  var usageListeners = [];
  var usageWanted = false;
  function usage() {
    usageWanted = true;
    return call("usage", {});
  }
  function onUsage(listener) {
    if (typeof listener !== "function") throw new TypeError("onUsage needs a function");
    usageListeners.push(listener);
    if (!usageWanted) usage().catch(noop);
    return function () {
      var at = usageListeners.indexOf(listener);
      if (at >= 0) usageListeners.splice(at, 1);
    };
  }
  function usageEvent(data) {
    if (!data.usage || typeof data.usage !== "object") return;
    usageListeners.slice().forEach(function (listener) {
      try {
        listener(data.usage);
      } catch (error) {}
    });
  }
  // nest.ask: a small text request to Claude, which Nest limits per artifact and day. The
  // app's refusals (budget, disabled, busy, unavailable) reach the page as they are.
  function ask(prompt, options) {
    if (typeof prompt !== "string" || prompt.length < 1 || prompt.length > 8000) {
      return Promise.reject(failure("bad_request", "ask needs a prompt of 1 to 8,000 characters"));
    }
    var given = options === undefined ? {} : options;
    var system = given && typeof given === "object" ? given.system : null;
    var fits = system === undefined || (typeof system === "string" && system.length <= 4000);
    if (!given || typeof given !== "object" || !fits) {
      return Promise.reject(
        failure(
          "bad_request",
          "ask's options are an object with an optional system of up to 4,000 characters"
        )
      );
    }
    var request = { prompt: prompt };
    if (system !== undefined) request.system = system;
    return call("ask", request).then(readsAsText);
  }
  // The answer stays {text, remaining, limit}, but reads as its text where a string is wanted
  // (el.textContent = await nest.ask(...)), through hidden toString and toPrimitive.
  function readsAsText(answer) {
    if (!answer || typeof answer !== "object" || typeof answer.text !== "string") return answer;
    var text = answer.text;
    try {
      Object.defineProperty(answer, "toString", {
        value: function () {
          return text;
        },
      });
      Object.defineProperty(answer, Symbol.toPrimitive, {
        value: function (hint) {
          return hint === "number" ? Number(text) : text;
        },
      });
    } catch (error) {}
    return answer;
  }
  // Host events: storage changes made elsewhere and usage updates.
  function hostEvent(data) {
    if (!data || typeof data !== "object" || data.nest !== 1) return;
    if (data.event === "usage") return usageEvent(data);
    if (data.event === "storage") storageEvent(data);
  }
  // A change made elsewhere (another device, the reader's clear). A key the page is about to
  // write keeps the page's value; the echo of a value the page has is not a change.
  function storageEvent(data) {
    if (data.clear === true) {
      wipe();
      if (batch) {
        Object.keys(batch.set).forEach(function (key) {
          put(key, batch.set[key]);
        });
      }
      return notify(null, null);
    }
    var key = data.key;
    var value = typeof data.value === "string" ? data.value : null;
    if (typeof key !== "string" || (batch && (key in batch.set || key in batch.remove))) return;
    if ((has(key) ? cache[key] : null) === value) return;
    if (value === null) drop(key);
    else put(key, value);
    notify(key, value);
  }
  var storage = {
    get: function (key) {
      key = String(key);
      return has(key) ? cache[key] : null;
    },
    set: storageSet,
    remove: storageRemove,
    keys: function () {
      return Object.keys(cache);
    },
    clear: storageClear,
    onChange: function (listener) {
      if (typeof listener !== "function") throw new TypeError("onChange needs a function");
      listeners.push(listener);
      return function () {
        var at = listeners.indexOf(listener);
        if (at >= 0) listeners.splice(at, 1);
      };
    },
  };
  // localStorage and sessionStorage for pages written for them: the first kept by the app
  // through nest.storage, the second in memory for the page's life. Both coerce to strings
  // and allow storage.name access like the real ones.
  function quotaError(message) {
    try {
      return new DOMException(message, "QuotaExceededError");
    } catch (error) {
      var fallback = new Error(message);
      fallback.name = "QuotaExceededError";
      return fallback;
    }
  }
  function keyAt(keys, index) {
    var at = Math.floor(Number(index)) || 0;
    return at >= 0 && at < keys.length ? keys[at] : null;
  }
  // A write with localStorage's manners: refused at once over a cap, else written through.
  function writeNow(key, value) {
    var problem = refusal(key, value);
    if (problem) throw quotaError(problem.message);
    storageSet(key, value).catch(noop);
  }
  function storageLike(backend) {
    var methods = {
      getItem: function (key) {
        return backend.get(String(key));
      },
      setItem: function (key, value) {
        backend.set(String(key), String(value));
      },
      removeItem: function (key) {
        backend.remove(String(key));
      },
      clear: function () {
        backend.clear();
      },
      key: function (index) {
        return keyAt(backend.keys(), index);
      },
    };
    function value(name) {
      return typeof name === "string" ? backend.get(name) : null;
    }
    return new Proxy(Object.create(null), {
      get: function (target, name) {
        if (name === "length") return backend.keys().length;
        if (typeof name === "string" && Object.prototype.hasOwnProperty.call(methods, name)) {
          return methods[name];
        }
        var found = value(name);
        return found === null ? undefined : found;
      },
      set: function (target, name, next) {
        if (typeof name === "string") methods.setItem(name, next);
        return true;
      },
      deleteProperty: function (target, name) {
        if (typeof name === "string") methods.removeItem(name);
        return true;
      },
      has: function (target, name) {
        return value(name) !== null;
      },
      ownKeys: function () {
        return backend.keys();
      },
      getOwnPropertyDescriptor: function (target, name) {
        var found = value(name);
        if (found === null) return undefined;
        return { value: found, writable: true, enumerable: true, configurable: true };
      },
    });
  }
  var local = storageLike({
    get: storage.get,
    set: writeNow,
    remove: function (key) {
      storageRemove(key).catch(noop);
    },
    clear: function () {
      storageClear().catch(noop);
    },
    keys: storage.keys,
  });
  // nest.storage answers to the Storage names too, for pages written for localStorage:
  // setItem coerces to strings and changes the cache at once, writing through as set does.
  storage.getItem = storage.get;
  storage.setItem = function (key, value) {
    writeNow(String(key), String(value));
  };
  storage.removeItem = function (key) {
    storageRemove(key).catch(noop);
  };
  storage.key = function (index) {
    return keyAt(storage.keys(), index);
  };
  Object.defineProperty(storage, "length", {
    enumerable: true,
    get: function () {
      return storage.keys().length;
    },
  });
  Object.freeze(storage);
  var memory = Object.create(null);
  var session = storageLike({
    get: function (key) {
      return Object.prototype.hasOwnProperty.call(memory, key) ? memory[key] : null;
    },
    set: function (key, value) {
      memory[key] = value;
    },
    remove: function (key) {
      delete memory[key];
    },
    clear: function () {
      memory = Object.create(null);
    },
    keys: function () {
      return Object.keys(memory);
    },
  });
  function install(name, value) {
    try {
      Object.defineProperty(window, name, { value: value, configurable: true, enumerable: true });
    } catch (error) {}
  }
  install("localStorage", local);
  install("sessionStorage", session);
  // nest.files: the artifact's own files, from the init data.
  var files = (Array.isArray(init.files) ? init.files : []).filter(function (file) {
    return file && typeof file.path === "string" && typeof file.data === "string";
  });
  var blobs = Object.create(null);
  function fileAt(path) {
    for (var at = 0; at < files.length; at += 1) {
      if (files[at].path === path) return files[at];
    }
    throw failure("bad_request", "This artifact has no file " + path);
  }
  function bytesOf(file) {
    var binary = atob(file.data);
    var bytes = new Uint8Array(binary.length);
    for (var at = 0; at < binary.length; at += 1) bytes[at] = binary.charCodeAt(at);
    return bytes;
  }
  function mimeOf(file) {
    return typeof file.mime === "string" ? file.mime : "application/octet-stream";
  }
  var fileApi = Object.freeze({
    list: function () {
      return files.map(function (file) {
        return { path: file.path, size: file.size, mime: mimeOf(file) };
      });
    },
    text: function (path) {
      return new TextDecoder().decode(bytesOf(fileAt(path)));
    },
    dataUrl: function (path) {
      var file = fileAt(path);
      return "data:" + mimeOf(file) + ";base64," + file.data;
    },
    blobUrl: function (path) {
      var file = fileAt(path);
      if (!blobs[path]) {
        blobs[path] = URL.createObjectURL(new Blob([bytesOf(file)], { type: mimeOf(file) }));
      }
      return blobs[path];
    },
  });
  // nest.saveFile: the app asks the user where to save it, or to confirm.
  function saveFile(options) {
    var file = options && typeof options === "object" ? options : {};
    var encoding = file.encoding === undefined ? "utf8" : file.encoding;
    var named = typeof file.name === "string" && file.name !== "";
    var encoded = encoding === "utf8" || encoding === "base64";
    if (!named || typeof file.content !== "string" || !encoded) {
      return Promise.reject(
        failure("bad_request", "saveFile needs a name, the content as a string and utf8 or base64")
      );
    }
    var mime = file.mime === undefined ? "application/octet-stream" : String(file.mime);
    var request = { name: file.name, content: file.content, encoding: encoding, mime: mime };
    return call("saveFile", request);
  }
  function printPage() {
    try {
      if (typeof realPrint === "function") realPrint.call(window);
    } catch (error) {}
  }
  if (!mac) {
    window.addEventListener("message", function (event) {
      if (event.source !== window.parent || window.parent === window) return;
      var data = event.data;
      if (data && typeof data === "object" && data.nest === 1 && data.event === "print") {
        return printPage();
      }
      var hosted = data && typeof data === "object" && data.event;
      if (hosted === "storage" || hosted === "usage") return hostEvent(data);
      settle(data);
    });
  } else {
    // The Mac sends host events by calling this from the app (evaluateJavaScript).
    Object.defineProperty(window, "__nestHost", {
      value: Object.freeze(function (event) {
        hostEvent(event);
      }),
    });
  }
  // The user's last click or key press, so a call that needs one is not made by accident
  // (a guard, not a security boundary: a page's own script can post to the app directly).
  function trust(event) {
    if (event && event.isTrusted === true) trusted = now();
  }
  window.addEventListener("click", trust, true);
  window.addEventListener("keydown", trust, true);
  document.addEventListener("click", onClick, true);
  window.open = function (url) {
    if (url !== undefined && url !== null && String(url) !== "") quietly(String(url));
    return null;
  };
  var api = { version: 1, openLink: openLink, storage: storage, files: fileApi };
  api.saveFile = saveFile;
  api.usage = usage;
  api.onUsage = onUsage;
  api.ask = ask;
  methods.forEach(function (name) {
    var action = userActions[name];
    api[name] = function (params) {
      if (action && !(now() - trusted <= 5000)) {
        return Promise.reject(failure("bad_request", action));
      }
      return call(name, params === undefined ? {} : params);
    };
  });
  Object.defineProperty(window, "nest", { value: Object.freeze(api), enumerable: true });
})();"""

# The bridge's methods besides openLink, each a plain call with its params; a new method is one
# more name here (and its handler in each app).
METHODS = ("saveDocument",)
# Methods the shim makes only right after a user's action (a click or key press in the last 5
# seconds), with the refusal otherwise: a guard against a save nobody asked for, not a security
# boundary (a page's script can post to the app directly).
USER_ACTIONS = {"saveDocument": "Saving needs a click on Save"}
SHIM = _SOURCE.replace("__METHODS__", json.dumps(list(METHODS))).replace(
    "__USER_ACTIONS__", json.dumps(USER_ACTIONS)
)
SHIM_TAG = f"<script>{SHIM}</script>"

_JSON_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    chr(0x2028): "\\u2028",
    chr(0x2029): "\\u2029",
}


def json_script(element_id: str, data: object) -> str:
    """Data in a JSON script element that nothing in it can end."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for raw, safe in _JSON_ESCAPES.items():
        text = text.replace(raw, safe)
    return f'<script type="application/json" id="{element_id}">{text}</script>'


def init_tag(init: Mapping[str, object]) -> str:
    """A page's initial data for the shim (B88 stage 3): `{storage: {key: value}, files:
    [{path, size, mime, data}]}`, base64 data. The shim reads it once and removes it.
    """
    return json_script("nest-init", dict(init))


# A leading doctype, after a BOM, whitespace and comments.
_DOCTYPE = re.compile(r"\ufeff?(?:\s|<!--.*?-->)*<!doctype[^>]*>", re.IGNORECASE | re.DOTALL)


def with_shim(document: str, init: Mapping[str, object] | None = None) -> str:
    """The document with the shim right after its leading doctype, else first (after a BOM),
    so it runs before any page script; its init data, when given, right before it (a script
    cannot read what is parsed after it).
    """
    found = _DOCTYPE.match(document)
    at = found.end() if found else len(document) - len(document.removeprefix("\ufeff"))
    data = init_tag(init) if init is not None else ""
    return document[:at] + data + SHIM_TAG + document[at:]
