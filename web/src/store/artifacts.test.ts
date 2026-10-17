import { describe, expect, it } from "vitest";
import type { Artifact, ArtifactFilter, JsonObject } from "../api/types.ts";
import { artifact, artifactDetail, event } from "../test/fixtures.ts";
import { artifactList, filterKey, matches } from "./artifacts.ts";
import { reduce } from "./reducer.ts";
import { initialState, type State } from "./state.ts";

const chat: ArtifactFilter = { session_id: "s1" };
const project: ArtifactFilter = { repo: "cv-page" };
const pixie: ArtifactFilter = { pixie_id: "p1" };

const older = artifact({ id: "a1", updated_at: "2026-10-17T09:00:00+00:00" });
const newer = artifact({ id: "a2", session_id: "s2", updated_at: "2026-10-17T10:00:00+02:00" });

function listed(lists: [ArtifactFilter, Artifact[]][]): State {
  return lists.reduce(
    (state, [filter, artifacts]) => reduce(state, { type: "artifacts", filter, artifacts }),
    initialState,
  );
}

const global = (type: string, payload: JsonObject) =>
  reduce(listed([]), { type: "event", event: event({ id: 9, session_id: null, type, payload }) });

const apply = (state: State, type: string, payload: JsonObject, session: string | null = null) =>
  reduce(state, { type: "event", event: event({ id: 9, session_id: session, type, payload }) });

const ids = (state: State, filter: ArtifactFilter) => artifactList(state, filter)?.map((a) => a.id);

describe("artifact filters", () => {
  it("name a list the same whatever their order", () => {
    expect(filterKey({ session_id: "s1", repo: "r" })).toBe(
      filterKey({ repo: "r", session_id: "s1" }),
    );
    expect(filterKey({})).not.toBe(filterKey(project));
  });

  it("match as the daemon's filters do, combined", () => {
    expect(matches(older, {})).toBe(true);
    expect(matches(older, { repo: "cv-page", session_id: "s1" })).toBe(true);
    expect(matches(older, { repo: "cv-page", session_id: "s2" })).toBe(false);
    expect(matches(older, pixie)).toBe(false);
  });
});

describe("artifact lists", () => {
  it("are unknown until loaded, then newest first by when they were saved", () => {
    expect(artifactList(initialState, chat)).toBeNull();
    // 10:00 at +02:00 is 08:00 UTC, before 09:00 UTC.
    const state = listed([[{}, [newer, older]]]);
    expect(ids(state, {})).toEqual(["a1", "a2"]);
  });

  it("take a saved artifact into each loaded list it belongs in, at the top", () => {
    const state = listed([
      [chat, [older]],
      [project, [older]],
      [pixie, []],
    ]);
    const saved = artifact({ id: "a3", updated_at: "2026-10-17T11:00:00+00:00" });
    const next = apply(state, "artifact.saved", {
      artifact: saved as unknown as JsonObject,
      action: "created",
      version: 1,
      unseen: 4,
    });
    expect(ids(next, chat)).toEqual(["a3", "a1"]);
    expect(ids(next, project)).toEqual(["a3", "a1"]);
    expect(ids(next, pixie)).toEqual([]);
    expect(next.unseenArtifacts).toBe(4);

    // A new version of one listed replaces it and moves it up.
    const updated = {
      ...older,
      title: "Renamed",
      latest_version: 2,
      updated_at: "2026-10-17T12:00:00+00:00",
    };
    const again = apply(next, "artifact.saved", {
      artifact: updated,
      action: "updated",
      version: 2,
      unseen: 4,
    });
    expect(ids(again, chat)).toEqual(["a1", "a3"]);
    expect(artifactList(again, chat)?.[0]?.title).toBe("Renamed");
  });

  it("mark one seen, and drop one deleted, setting the badge from the event", () => {
    const state = listed([[chat, [older]]]);
    const seen = apply(state, "artifact.seen", { artifact_id: "a1", unseen: 0 });
    expect(artifactList(seen, chat)?.[0]?.seen).toBe(true);
    expect(seen.unseenArtifacts).toBe(0);
    // Seen again, or an unknown one, changes nothing but the count.
    expect(apply(seen, "artifact.seen", { artifact_id: "a1", unseen: 0 }).artifacts).toBe(
      seen.artifacts,
    );
    expect(apply(seen, "artifact.seen", { artifact_id: "zz", unseen: 0 }).artifacts).toBe(
      seen.artifacts,
    );

    const deleted = apply(seen, "artifact.deleted", { artifact_id: "a1", unseen: 0 });
    expect(ids(deleted, chat)).toEqual([]);
    expect(deleted.artifactsGone).toEqual({ a1: true });
    expect(deleted.artifacts).toEqual({});
  });

  it("change nothing for an event that names no artifact", () => {
    const state = listed([[chat, [older]]]);
    expect(apply(state, "artifact.seen", {}).artifacts).toBe(state.artifacts);
    expect(ids(apply(state, "artifact.deleted", {}), chat)).toEqual(["a1"]);
  });

  it("keep the badge when an event leaves its count out", () => {
    const state = reduce(initialState, { type: "unseenArtifacts", unseen: 3 });
    expect(apply(state, "artifact.seen", { artifact_id: "a1" }).unseenArtifacts).toBe(3);
    expect(global("artifact.deleted", { artifact_id: "a1", unseen: 1 }).unseenArtifacts).toBe(1);
  });

  it("keep a deleted chat's artifacts, marked as from a deleted chat", () => {
    const kept = artifact({ id: "a3", session_id: "s3" });
    const state = listed([[project, [older, kept]]]);
    const next = apply(state, "session.deleted", { session_id: "s1" });
    expect(next.artifacts.a1?.chat_deleted).toBe(true);
    expect(next.artifacts.a3?.chat_deleted).toBe(false);
    expect(ids(next, project)).toEqual(["a1", "a3"]);
    // Nothing of that chat: the artifacts stay as they were.
    expect(apply(next, "session.deleted", { session_id: "s1" }).artifacts).toBe(next.artifacts);
  });

  it("mark a deleted pixie's artifacts as from a deleted chat", () => {
    const own = artifact({ id: "a4", pixie_id: "p1", pixie_name: "Tester", repo: "pixie:p1" });
    const next = apply(listed([[pixie, [own]]]), "pixie.deleted", { pixie_id: "p1" });
    expect(next.artifacts.a4).toMatchObject({ chat_deleted: true, pixie_name: "Tester" });
    expect(ids(next, pixie)).toEqual(["a4"]);
  });

  it("keep an artifact looked up by itself, without its versions", () => {
    const state = reduce(initialState, {
      type: "artifact",
      artifact: artifactDetail({ latest_version: 2 }),
    });
    expect(state.artifacts.a1).toEqual(artifact({ latest_version: 2 }));
    expect(state.artifactLists).toEqual({});
  });
});
