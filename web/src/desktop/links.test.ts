// Every link in the window opens in the system's browser, and only a web or mail link opens.
import { afterEach, describe, expect, it, vi } from "vitest";
import { safeLink } from "./bridge.ts";
import { routeLinkClick } from "./links.ts";

function click(html: string, button = 0) {
  document.body.innerHTML = html;
  const target = document.querySelector("[data-hit]") ?? document.body;
  const event = new MouseEvent(button === 1 ? "auxclick" : "click", {
    bubbles: true,
    cancelable: true,
    button,
  });
  Object.defineProperty(event, "target", { value: target });
  const openExternal = vi.fn(() => Promise.resolve());
  const openBrowserWindow = vi.fn(() => Promise.resolve(null));
  const handled = routeLinkClick(event, { openExternal, openBrowserWindow });
  return { handled, prevented: event.defaultPrevented, openExternal, openBrowserWindow };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("links in the desktop window", () => {
  it("opens a pull request, issue or chat link in the system's browser, not in Nest", () => {
    const pr = click(
      '<a href="https://github.com/o/r/pull/7" target="_blank"><b data-hit>7</b></a>',
    );
    expect(pr).toMatchObject({ handled: true, prevented: true });
    expect(pr.openExternal).toHaveBeenCalledWith("https://github.com/o/r/pull/7");
    const mail = click('<a data-hit href="mailto:me@example.com">mail</a>', 1);
    expect(mail.openExternal).toHaveBeenCalledWith("mailto:me@example.com");
  });

  it("opens a dev server on this computer in a Nest browser window", () => {
    const local = click('<a data-hit href="http://localhost:5173/">app</a>');
    expect(local.openBrowserWindow).toHaveBeenCalledWith("http://localhost:5173/");
    expect(local.openExternal).not.toHaveBeenCalled();
  });

  it("holds back every other link, relative ones included, without opening it", () => {
    for (const href of [
      "javascript:alert(1)",
      "file:///etc/passwd",
      "vscode://x",
      "/api/x",
      "a.html",
    ]) {
      const result = click(`<a data-hit href="${href}">x</a>`);
      expect(result.prevented, href).toBe(true);
      expect(result.openExternal, href).not.toHaveBeenCalled();
    }
  });

  it("leaves in-page anchors, downloads of the page's files and other buttons alone", () => {
    expect(click('<a data-hit href="#notes">x</a>')).toMatchObject({
      handled: false,
      prevented: false,
    });
    expect(click('<a data-hit download="a.txt" href="blob:http://x/1">x</a>').prevented).toBe(
      false,
    );
    expect(click("<p data-hit>text</p>").handled).toBe(false);
    expect(click('<a data-hit href="https://x.dev">x</a>', 2).handled).toBe(false);
  });

  it("allows only web and mail schemes", () => {
    expect(safeLink("HTTPS://Example.com/a")).toBe("https://example.com/a");
    expect(safeLink("mailto:a@b.c")).toBe("mailto:a@b.c");
    expect(safeLink("javascript:alert(1)")).toBeNull();
    expect(safeLink("not a url")).toBeNull();
  });
});
