import { act, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useStore } from "../../store/context.ts";
import { Markdown } from "../../ui/Markdown.tsx";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { memoryStorage } from "../../test/render.tsx";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { browserBridge, type Bridge } from "../bridge.ts";
import { BridgeContext } from "../context.ts";
import { FileLinks } from "./FileLinks.tsx";

function Toasts() {
  const { state } = useStore();
  return <p>{state.toast?.text}</p>;
}

function show(
  bridge: Bridge,
  folder: string | null,
  session: string | null = null,
  api = fakeApi(),
) {
  render(
    <StoreProvider api={api} connect={socketFactory().connect} storage={memoryStorage}>
      <BridgeContext value={bridge}>
        <FileLinks folder={folder} session={session}>
          <Markdown text="See `web/src/App.tsx:42`." />
        </FileLinks>
        <Toasts />
      </BridgeContext>
    </StoreProvider>,
  );
}

function appBridge(base: string, openTextFile: Bridge["openTextFile"]): Bridge {
  return {
    ...browserBridge({ search: "" }, null),
    native: true,
    daemon: () => Promise.resolve({ base, token: "t" }),
    openTextFile,
  };
}

describe("files named in a chat", () => {
  it("open through the app with the chat's folder, and a refusal says File not found", async () => {
    const open = vi.fn(() => Promise.reject(new Error("no")));
    show(appBridge("http://127.0.0.1:8765", open), "/home/me/project");
    (await screen.findByRole("link", { name: "web/src/App.tsx:42" })).click();
    expect(open).toHaveBeenCalledWith("web/src/App.tsx", "/home/me/project");
    expect(await screen.findByText("File not found")).toBeInTheDocument();
  });

  it("stay text for a daemon on another machine, a chat with no folder, or outside the app", async () => {
    show(appBridge("https://mini.ts.net", vi.fn()), "/home/me/project");
    show(appBridge("http://127.0.0.1:8765", vi.fn()), null);
    show(browserBridge({ search: "" }, null), "/home/me/project");
    await act(() => Promise.resolve());
    expect(screen.getAllByText("web/src/App.tsx:42")).toHaveLength(3);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("open in the viewer for a chat the daemon knows, with the editor one click away", async () => {
    const open = vi.fn(() => Promise.resolve());
    const api = fakeApi();
    api.namedFile.mockResolvedValue(new Blob(["const a = 1;\n"]));
    show(appBridge("http://127.0.0.1:8765", open), "/home/me/project", "s1", api);

    (await screen.findByRole("link", { name: "web/src/App.tsx:42" })).click();

    const sheet = await screen.findByRole("dialog", { name: "App.tsx" });
    expect(api.namedFile).toHaveBeenCalledWith("s1", "web/src/App.tsx");
    expect(open).not.toHaveBeenCalled();
    within(sheet).getByRole("button", { name: "Open in editor" }).click();
    expect(open).toHaveBeenCalledWith("web/src/App.tsx", "/home/me/project");
  });
});
