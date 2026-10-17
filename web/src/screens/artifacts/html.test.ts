import { describe, expect, it } from "vitest";
import { ARTIFACT_CSP, withCsp } from "./html.ts";

const parse = (html: string) => new DOMParser().parseFromString(withCsp(html), "text/html");

/** The policy meta, which must be the first thing in the parsed document's head. */
function firstInHead(doc: Document): Element | null {
  return doc.head.firstElementChild;
}

describe("the policy injected into an HTML artifact", () => {
  it("is the exact policy of the contract", () => {
    expect(ARTIFACT_CSP).toBe(
      "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
    );
  });

  it.each([
    [
      "a whole document",
      "<!doctype html><html lang='en'><head><title>T</title></head><body><p>Hi</p></body></html>",
    ],
    ["a document without a head", "<html><body><p>Hi</p></body></html>"],
    ["a fragment without html or head", "<p>Hi</p><script>document.title = 'x'</script>"],
    [
      "a head with attributes after whitespace",
      "\n  <!DOCTYPE html>\n<html>\n<head data-x='1'><meta charset='utf-8'></head><p>Hi</p>",
    ],
    ["an empty document", ""],
  ])("comes first in the head of %s", (_name, html) => {
    const doc = parse(html);
    const meta = firstInHead(doc);
    expect(meta?.tagName).toBe("META");
    expect(meta?.getAttribute("http-equiv")).toBe("Content-Security-Policy");
    expect(meta?.getAttribute("content")).toBe(ARTIFACT_CSP);
    expect(doc.querySelectorAll('meta[http-equiv="Content-Security-Policy"]')).toHaveLength(1);
  });

  it("keeps the document's own head, body and doctype", () => {
    const doc = parse(
      "<!doctype html><html lang='en'><head><title>Report</title></head><body><p>Hi</p></body></html>",
    );
    expect(doc.compatMode).toBe("CSS1Compat");
    expect(doc.documentElement.lang).toBe("en");
    expect(doc.title).toBe("Report");
    expect(doc.head.children[1]?.tagName).toBe("TITLE");
    expect(doc.body.textContent).toBe("Hi");
  });

  it("cannot be steered into a comment or a script's text by a fake head", () => {
    const tricks = [
      "<!-- <head> --><html><head></head><body>x</body></html>",
      "<script>var s = '<head>'</script><p>x</p>",
      "<title><head></title><p>x</p>",
    ];
    for (const html of tricks) {
      const doc = parse(html);
      expect(firstInHead(doc)?.getAttribute("content")).toBe(ARTIFACT_CSP);
    }
  });

  it("leaves the content after the meta as written", () => {
    expect(withCsp("<p>Hi</p>")).toBe(
      `<meta http-equiv="Content-Security-Policy" content="${ARTIFACT_CSP}"><p>Hi</p>`,
    );
    expect(withCsp("<!doctype html><p>Hi</p>")).toBe(
      `<!doctype html><meta http-equiv="Content-Security-Policy" content="${ARTIFACT_CSP}"><p>Hi</p>`,
    );
  });
});
