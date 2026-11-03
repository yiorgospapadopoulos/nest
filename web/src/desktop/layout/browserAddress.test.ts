// The browser pane's address field reads what is typed as the Mac's BrowserAddress
// (NestKitTests BrowserTests): ports open on localhost, hosts over http or https, the rest
// is a web search.
import { describe, expect, it } from "vitest";
import { browserAddress } from "./tools.ts";

describe("the browser pane's address field", () => {
  it.each([
    ["3000", "http://localhost:3000"],
    [":5173", "http://localhost:5173"],
    ["localhost", "http://localhost"],
    ["localhost:3000/about", "http://localhost:3000/about"],
    ["LOCALHOST:8000", "http://LOCALHOST:8000"],
    ["127.0.0.1:8000", "http://127.0.0.1:8000"],
    ["0.0.0.0:4321", "http://0.0.0.0:4321"],
    ["[::1]:3000", "http://[::1]:3000"],
    ["devbox:8080/x", "http://devbox:8080/x"],
    ["example.com", "https://example.com"],
    ["github.com/me/todo-ui?tab=pulls", "https://github.com/me/todo-ui?tab=pulls"],
    ["http://example.com/a", "http://example.com/a"],
    ["https://localhost:8443", "https://localhost:8443"],
    ["  docs.swift.org  ", "https://docs.swift.org"],
  ])("opens %s as %s", (input, expected) => {
    expect(browserAddress(input)).toBe(expected);
  });

  it.each(["swift testing", "readme", "70000", "host:notaport"])("searches for %s", (input) => {
    const url = new URL(browserAddress(input) ?? "");
    expect(url.host).toBe("duckduckgo.com");
    expect(url.searchParams.get("q")).toBe(input);
  });

  it("opens nothing for blank input", () => {
    expect(browserAddress("  ")).toBeNull();
  });
});
