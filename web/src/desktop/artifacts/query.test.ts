// Ported from NestKitTests' ArtifactsTests (queries, the view's scope and its selection).
import { describe, expect, it } from "vitest";
import { artifact, pixie, session } from "../../test/fixtures.ts";
import { initialState } from "../../store/state.ts";
import { withList } from "../../store/artifacts.ts";
import {
  artifactScope,
  filterOf,
  keptSelection,
  listed,
  matches,
  type ArtifactQuery,
} from "./query.ts";

const chat = artifact({ id: "a1" });
const fromPixie = artifact({ id: "p", repo: "pixie:p1", session_id: "pc", pixie_id: "p1" });

describe("artifact queries", () => {
  it("match their artifacts", () => {
    expect(matches({ chat: "s1" }, chat)).toBe(true);
    expect(matches({ chat: "s2" }, chat)).toBe(false);
    expect(matches({ project: "todo-ui" }, chat)).toBe(true);
    expect(matches({ project: "todo-ui" }, fromPixie)).toBe(false);
    expect(matches({ pixie: "p1" }, fromPixie)).toBe(true);
    expect(matches({ pixie: "p1" }, chat)).toBe(false);
    expect(matches({ pixies: true }, fromPixie)).toBe(true);
    expect(matches({ pixies: true }, chat)).toBe(false);
  });

  it("list every pixie's from the unfiltered list, and only those", () => {
    const query: ArtifactQuery = { pixies: true };
    expect(filterOf(query)).toEqual({});
    const state = withList(initialState, filterOf(query), [chat, fromPixie]);
    expect(listed(state, query)?.map((a) => a.id)).toEqual(["p"]);
    expect(listed(initialState, query)).toBeNull();
  });
});

describe("the Artifacts view's scope", () => {
  const sessions = { s1: session({ id: "s1" }) };
  const pixies = { p1: pixie({ id: "p1" }) };

  it("is the focused chat's with the whole project, or the project alone", () => {
    expect(artifactScope({ project: "todo-ui", focused: "s1", sessions, pixies })).toEqual({
      narrow: { chat: "s1" },
      wide: { project: "todo-ui" },
    });
    // A terminal or another pane that is no chat leaves only the project.
    expect(artifactScope({ project: "todo-ui", focused: "term:1", sessions, pixies })).toEqual({
      narrow: null,
      wide: { project: "todo-ui" },
    });
  });

  it("is the focused pixie's with every pixie's in the Pixies tab", () => {
    expect(artifactScope({ project: null, focused: "p1", sessions, pixies })).toEqual({
      narrow: { pixie: "p1" },
      wide: { pixies: true },
    });
    expect(artifactScope({ project: null, focused: null, sessions, pixies })).toEqual({
      narrow: null,
      wide: { pixies: true },
    });
  });
});

describe("the reader's selection", () => {
  const newer = artifact({ id: "a2", latest_version: 3 });
  const older = artifact({ id: "a1", latest_version: 2 });

  it("stays while the list holds it", () => {
    expect(keptSelection([newer, older], { id: "a1", version: 1 })).toEqual({
      id: "a1",
      version: 1,
    });
  });

  it("moves to the newest at its latest version when the list lacks it, or none", () => {
    expect(keptSelection([newer, older], { id: "gone", version: 1 })).toEqual({
      id: "a2",
      version: 3,
    });
    expect(keptSelection([newer, older], null)).toEqual({ id: "a2", version: 3 });
    expect(keptSelection([], { id: "a1", version: 1 })).toBeNull();
  });
});
