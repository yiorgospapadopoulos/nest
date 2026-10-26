import { describe, expect, it } from "vitest";
import { repo } from "../test/fixtures.ts";
import { GENERAL, projectName, repoNamed } from "./general.ts";

describe("General (B110)", () => {
  it("finds a registered project, General, or nothing", () => {
    const app = repo("app");

    expect(repoNamed([app], "app")).toBe(app);
    expect(repoNamed([app], GENERAL)).toMatchObject({ name: "general", git: false });
    expect(repoNamed([app], "gone")).toBeUndefined();
  });

  it("names General's chats General and a project by its name", () => {
    expect(projectName(GENERAL)).toBe("General");
    expect(projectName("app")).toBe("app");
  });
});
