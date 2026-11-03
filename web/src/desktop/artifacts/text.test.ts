// Ported from NestKitTests (ArtifactsTests, ArtifactPageDataTests, ArtifactAskTests).
import { describe, expect, it } from "vitest";
import { artifact, artifactContent } from "../../test/fixtures.ts";
import { asksText, fileName, line, origin, pdfName, savedText, when } from "./text.ts";

const NOW = new Date("2026-10-17T10:00:00Z");
const ago = (minutes: number) => new Date(NOW.getTime() - minutes * 60_000).toISOString();

describe("the artifact views' words", () => {
  it("name who made it", () => {
    expect(origin(artifact({ pixie_id: "p1", pixie_name: "Reviewer" }))).toBe("Reviewer");
    expect(origin(artifact({ chat_title: "Pick a queue" }))).toBe("Pick a queue");
    expect(origin(artifact({ chat_title: "Pick a queue", chat_deleted: true }))).toBe(
      "Deleted chat",
    );
    expect(origin(artifact({ chat_title: null }))).toBe("Deleted chat");
  });

  it("say when, as the Mac's short elapsed times", () => {
    expect(when(ago(0.5), NOW)).toBe("now");
    expect(when(ago(9), NOW)).toBe("9m ago");
    expect(when(ago(125), NOW)).toBe("2h 5m ago");
    expect(when(ago(120), NOW)).toBe("2h ago");
    expect(when(ago(60 * 50), NOW)).toBe("2d ago");
  });

  it("put what the page stored and today's asks in the reader's line", () => {
    const html = artifact({ kind: "html", chat_title: "Pick a queue" });
    const saved = NOW.toISOString();
    expect(line(html, "agent", saved, NOW, 12_000, null)).toBe(
      "HTML · Pick a queue · saved now · 12 KB stored",
    );
    expect(line(html, "agent", saved, NOW, 0, null)).toBe("HTML · Pick a queue · saved now");
    expect(line(html, "user", ago(3), NOW, 2_000, { remaining: 19, limit: 20 })).toBe(
      "HTML · Pick a queue · Edited by you 3m ago · 2 KB stored · 1 of 20 asks today",
    );
  });

  it("count today's asks within the limit", () => {
    expect(asksText({ remaining: 17, limit: 20 })).toBe("3 of 20 asks today");
    expect(asksText({ remaining: 0, limit: 20 })).toBe("20 of 20 asks today");
    expect(asksText({ remaining: 25, limit: 20 })).toBe("0 of 20 asks today");
  });

  it("make a title a file name", () => {
    expect(fileName("Options compared", "markdown")).toBe("Options compared.md");
    expect(fileName("A/B: tests?  <v2>", "html")).toBe("A B tests v2.html");
    expect(fileName("..hidden. ", "markdown")).toBe("hidden.md");
    expect(fileName("\n\t", "markdown")).toBe("Artifact.md");
    expect(fileName("x".repeat(300), "html")).toHaveLength(125);
    expect(fileName("Plan", "design")).toBe("Plan.json");
    expect(pdfName("Q3: review")).toBe("Q3 review.pdf");
    expect(pdfName("")).toBe("Artifact.pdf");
  });

  it("save a multi-file page as its built page, anything else as written", () => {
    const files = [{ path: "app.js", size: 3, mime: "text/javascript" }];
    const page = "<!doctype html><p>built</p>";
    const html = artifactContent({ kind: "html", content: "<p>src</p>", page, files });
    expect(savedText(html)).toBe(page);
    expect(savedText({ ...html, files: [] })).toBe("<p>src</p>");
    expect(savedText({ ...html, kind: "document" })).toBe("<p>src</p>");
  });
});
