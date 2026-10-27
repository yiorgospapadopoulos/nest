import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { JsonObject } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { artifact, artifactContent, usagePeriod } from "../../test/fixtures.ts";
import { succeed } from "./bridge.ts";
import { frameIn, openChat, openHistory, showing } from "../../test/artifacts.ts";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a page that reads usage and asks Claude (B88)", () => {
  const helper = artifact({ id: "h1", title: "Ask helper", kind: "html", seen: true });

  async function readingHelper(api = fakeApi()) {
    api.artifacts.mockResolvedValue([helper]);
    api.artifactVersion.mockImplementation((id, version) =>
      Promise.resolve(
        artifactContent({
          artifact_id: id,
          version,
          kind: "html",
          title: "Ask helper",
          content: "<p>Helper</p>",
        }),
      ),
    );
    const rendered = await openChat({ api });
    await openHistory(rendered);
    await rendered.user.click(await screen.findByRole("button", { name: /^Ask helper/ }));
    const sheet = await screen.findByRole("dialog", { name: "Ask helper" });
    await showing(sheet, "Helper");
    const page = frameIn(sheet).contentWindow;
    if (page === null) throw new Error("no window");
    const sent = vi.spyOn(page, "postMessage");
    const replies = () => sent.mock.calls.map(([reply]) => reply as unknown);
    const call = (id: string, method: string, params: unknown) => {
      act(() => {
        window.dispatchEvent(
          new MessageEvent("message", { data: { nest: 1, id, method, params }, source: page }),
        );
      });
    };
    const asked = (payload: JsonObject) => {
      rendered.push({ id: null, type: "artifact.ask", payload });
    };
    return { ...rendered, api, sheet, replies, call, asked };
  }

  const refused = (id: string, code: string, message: string = expect.any(String) as string) => ({
    nest: 1,
    id,
    ok: false,
    error: { code, message },
  });
  const usage = {
    limits: { five_hour: { utilization: 0.3, resets_at: null }, seven_day: null },
    today: { tokens: usagePeriod().tokens.total, sessions: usagePeriod().sessions },
    week: { tokens: usagePeriod().tokens.total, sessions: usagePeriod().sessions },
  };

  it("answers usage with the Usage page's numbers", async () => {
    const { replies, call } = await readingHelper();
    call("1", "usage", {});
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", usage)]);
    });
  });

  it("answers unavailable when usage cannot be read", async () => {
    const api = fakeApi();
    api.usageLimits.mockRejectedValue(new Error("offline"));
    const { replies, call } = await readingHelper(api);
    call("1", "usage", {});
    await waitFor(() => {
      expect(replies()).toEqual([refused("1", "unavailable")]);
    });
  });

  it("sends fresh usage when it changes, only to a page that read it", async () => {
    const api = fakeApi();
    const { replies, call, push } = await readingHelper(api);
    push({ id: null, type: "usage.updated", payload: {} });
    await act(() => Promise.resolve());
    expect(replies()).toEqual([]);
    call("1", "usage", {});
    await waitFor(() => {
      expect(replies()).toHaveLength(1);
    });
    const reads = api.usageLimits.mock.calls.length;
    push({ id: null, type: "usage.updated", payload: {} });
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", usage), { nest: 1, event: "usage", usage }]);
    });
    expect(api.usageLimits.mock.calls.length).toBe(reads + 1);
  });

  it("drops a usage change it cannot read", async () => {
    const api = fakeApi();
    const { replies, call, push } = await readingHelper(api);
    call("1", "usage", {});
    await waitFor(() => {
      expect(replies()).toHaveLength(1);
    });
    api.usageLimits.mockRejectedValueOnce(new Error("offline"));
    push({ id: null, type: "usage.updated", payload: {} });
    await act(() => Promise.resolve());
    await act(() => Promise.resolve());
    expect(replies()).toHaveLength(1);
  });

  it("asks Claude, showing that it does, then today's count", async () => {
    const api = fakeApi();
    let answer: () => void = () => undefined;
    api.askArtifact.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          answer = () => {
            resolve({ text: "Autumn light", remaining: 19 });
          };
        }),
    );
    const { sheet, replies, call } = await readingHelper(api);
    expect(within(sheet).queryByRole("status")).toBeNull();
    call("1", "ask", { prompt: "A haiku", system: "Brief" });
    expect(await within(sheet).findByRole("status")).toHaveTextContent("Asking Claude...");
    expect(api.askArtifact).toHaveBeenCalledWith("h1", { prompt: "A haiku", system: "Brief" });
    act(() => {
      answer();
    });
    await waitFor(() => {
      expect(replies()).toEqual([succeed("1", { text: "Autumn light", remaining: 19 })]);
    });
    expect(within(sheet).queryByRole("status")).toBeNull();
    expect(sheet.querySelector(".afmeta")).toHaveTextContent("1 of 20 asks today");
  });

  it("takes the daily limit from the Mac when it says it", async () => {
    const api = fakeApi();
    api.askArtifact.mockResolvedValueOnce({ text: "Hi", remaining: 3, limit: 5 });
    const { sheet, call } = await readingHelper(api);
    call("1", "ask", { prompt: "Hi" });
    await waitFor(() => {
      expect(sheet.querySelector(".afmeta")).toHaveTextContent("2 of 5 asks today");
    });
  });

  it("maps the Mac's refusals to the page's error codes", async () => {
    const api = fakeApi();
    api.askArtifact
      .mockRejectedValueOnce(
        new ApiError(429, "Daily limit reached", null, { resets_at: "2026-10-20T00:00:00" }),
      )
      .mockRejectedValueOnce(new ApiError(403, "Asking is off"))
      .mockRejectedValueOnce(new ApiError(409, "Already asking"))
      .mockRejectedValueOnce(new ApiError(500, "Claude failed"))
      .mockRejectedValueOnce(new TypeError("Load failed"))
      .mockRejectedValueOnce(new ApiError(429, "Daily limit reached"));
    const { sheet, replies, call } = await readingHelper(api);
    for (const id of ["1", "2", "3", "4", "5", "6"]) {
      call(id, "ask", { prompt: "Hi" });
      await waitFor(() => {
        expect(replies()).toHaveLength(Number(id));
      });
    }
    const resets = new Date("2026-10-20T00:00:00").toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
    });
    expect(replies()).toEqual([
      refused("1", "budget", expect.stringContaining(resets) as string),
      refused("2", "disabled", "Asking is off"),
      refused("3", "busy", "Already asking"),
      refused("4", "unavailable", "Claude failed"),
      refused("5", "unavailable", "Claude could not answer."),
      refused("6", "budget", expect.stringContaining("Reset time unknown") as string),
    ]);
    expect((replies()[0] as { error: { message: string } }).error.message).toMatch(
      /^Today's asks for this page are used up\. Resets /,
    );
    expect(within(sheet).queryByRole("status")).toBeNull();
    expect(sheet.querySelector(".afmeta")).not.toHaveTextContent("asks today");
  });

  it("shows today's count on opening once the page has asked", async () => {
    const api = fakeApi();
    api.askStatus.mockResolvedValue({
      used: 4,
      limit: 30,
      remaining: 26,
      resets_at: null,
      enabled: true,
    });
    const { sheet } = await readingHelper(api);
    expect(api.askStatus).toHaveBeenCalledWith("h1");
    await waitFor(() => {
      expect(sheet.querySelector(".afmeta")).toHaveTextContent("4 of 30 asks today");
    });
  });

  it("shows no count on opening before any ask, or when it cannot be read", async () => {
    const api = fakeApi();
    api.askStatus.mockRejectedValueOnce(new Error("offline"));
    const { sheet } = await readingHelper(api);
    await act(() => Promise.resolve());
    expect(sheet.querySelector(".afmeta")).not.toHaveTextContent("asks today");
    await waitFor(() => {
      expect(api.askStatus).toHaveBeenCalledTimes(1);
    });
  });

  it("shows another device's ask from the Mac's events", async () => {
    const { sheet, asked } = await readingHelper();
    asked({ artifact_id: "other", state: "started", remaining: 4 });
    expect(within(sheet).queryByRole("status")).toBeNull();
    asked({ artifact_id: "h1", state: "started", remaining: 18 });
    expect(within(sheet).getByRole("status")).toHaveTextContent("Asking Claude...");
    expect(sheet.querySelector(".afmeta")).not.toHaveTextContent("asks today");
    asked({ artifact_id: "h1", state: "finished", remaining: 17 });
    expect(within(sheet).queryByRole("status")).toBeNull();
    expect(sheet.querySelector(".afmeta")).toHaveTextContent("3 of 20 asks today");
    asked({ artifact_id: "h1", state: "finished", remaining: 9, limit: 10 });
    expect(sheet.querySelector(".afmeta")).toHaveTextContent("1 of 10 asks today");
    // A finish that does not say what is left keeps the count.
    asked({ artifact_id: "h1", state: "finished" });
    expect(sheet.querySelector(".afmeta")).toHaveTextContent("1 of 10 asks today");
  });
});
